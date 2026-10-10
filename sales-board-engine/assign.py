"""Hands out upcoming appointments to reps, following assignment_rules.json (the one rules file).
The plan with the most expected closes (close chance + same-day weight x same-day chance) that fits the rules,
solved over every upcoming day at once so daily and weekly limits work together.
Usage: python assign.py <out dir> <job export csv> [today]   (reads <out dir>/scores.json, writes <out dir>/plan.json)"""
import json, math, sys
from pathlib import Path
from datetime import datetime
import numpy as np, pandas as pd
from scipy.optimize import milp, LinearConstraint, Bounds
from scipy.sparse import lil_matrix
import engine as E
import rr_metrics as rr

RULES = json.loads((E.HERE / "assignment_rules.json").read_text())
ZC = json.loads((E.HERE / "zip_centers.json").read_text())
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

def roster():
    return {k: v for k, v in RULES["roster"].items() if not k.startswith("_") and v.get("active", True)}

def miles(z1, z2):
    if z1 not in ZC or z2 not in ZC: return 15.0
    (x1, y1), (x2, y2) = ZC[z1], ZC[z2]
    return math.hypot((x1 - x2) * 69 * math.cos(math.radians(40.8)), (y1 - y2) * 69)

def hm(t): return None if not t else int(t[:2]) * 60 + int(t[3:5])

def is_spec_counted():
    return RULES["weekly_order"]["specialty_counts_toward_week"]

# ---------------- ratings ----------------
def rep_status(df, today):
    """Rating, limits, Hero's Journey stage, yearly promise for every active rep."""
    today = pd.Timestamp(today).normalize(); RT = RULES["ratings"]; HJ = RULES["hero_journey"]
    wk0 = today - pd.Timedelta(days=today.dayofweek)
    first = df.groupby("Primary Salesperson")["Initial Appointment Date"].min()
    spec = df["Job Trade Type"].fillna("").str.contains("Signature Roofing")
    issued = df["Initial Appointment Date"].notna() & ~df._cb & ~df._wt.isin(rr.WT["contacts_leads_appointments_exclude"]) & ~df._dead.isin(rr.DR["leads_and_appointments_exclude"])
    if not is_spec_counted(): issued &= ~spec
    out = {}
    for r, info in roster().items():
        start = pd.Timestamp(info["start_date"]) if info.get("start_date") else first.get(r, today) - pd.Timedelta(days=HJ["leads_start_day"] - 1)   # no start date: assume leads began on Day 16
        day_n = (today - start).days + 1
        def close(days):
            s, e = rr.rolling(today, days); m = rr.metrics(df, s, e, reps=[r])
            return m["close_sold_team"], m["close_sits_team"]
        sold, sits = close(RT["window_days"]); window = RT["window_days"]
        if sits < RT["min_sits_in_window"]:
            sold, sits = close(RT["fallback_window_days"]); window = RT["fallback_window_days"]
        rate = sold / sits if sits else None
        note = None
        if info["lane"] == "commercial": rating = "Lane"
        elif day_n <= RT["onboarding_days"]: rating = "New"
        elif rate is not None and rate >= RT["beast_at_or_above"]: rating = "Beast"
        elif rate is not None and rate >= RT["tenured_at_or_above"]: rating = "Tenured"
        else: rating = "Coaching"
        lim = dict(RT["limits"][rating])
        if rating == "New":
            leads_start = start + pd.Timedelta(days=HJ["leads_start_day"] - 1)
            if day_n < HJ["leads_start_day"]: lim.update(week_min=0, week_cap=0); note = f"Day {day_n}: training, leads start Day {HJ['leads_start_day']}"
            elif day_n <= HJ["ramp_until_day"]: lim.update(week_min=HJ["ramp_per_week"], week_cap=HJ["ramp_per_week"]); note = f"Day {day_n}: first leads, {HJ['ramp_per_week']} a week"
            else:
                m = rr.metrics(df, leads_start, today, reps=[r]); c = m["close_sold_team"] / m["close_sits_team"] if m["close_sits_team"] else 0
                if c >= HJ["day29_checkpoint_close"]: lim.update(week_min=HJ["full_volume_per_week"]); note = f"Day {day_n}: full volume ({c:.0%} since Day 1)"
                else: lim.update(week_min=0); note = f"Day {day_n}: under {HJ['day29_checkpoint_close']:.0%} since Day 1 ({c:.0%}), management review"
        # yearly promise: appointments issued per week since leads started
        ls = start + pd.Timedelta(days=HJ["leads_start_day"] - 1)
        n_iss = int((issued & (df["Primary Salesperson"] == r) & (df["Initial Appointment Date"] >= ls) & (df["Initial Appointment Date"] < today)).sum())
        weeks = max(1.0, (today - ls).days / 7)
        avg = n_iss / weeks if today > ls else None
        behind = avg is not None and avg < RULES["yearly_promise"]["per_week_average"] and rating in ("New", "Coaching")
        done = int((issued & (df["Primary Salesperson"] == r) & (df["Initial Appointment Date"] >= wk0) & (df["Initial Appointment Date"] < today)).sum())
        out[r] = dict(rating=rating, close=None if rate is None else round(rate, 3), sits=int(sits), window=window, day=day_n, limits=lim,
                      note=note, promise_avg=None if avg is None else round(avg, 1), behind_promise=bool(behind), this_week_so_far=done,
                      can_bend=rating in RULES["bends"]["who_can_bend"] or (RULES["bends"]["last_resort"]["enabled"] and rating in RULES["bends"]["last_resort"]["who"]))
    return out

# ---------------- plan ----------------
def bend_cost(rating):
    B = RULES["bends"]
    return B["penalty"][rating] if rating in B["penalty"] else B["last_resort"]["penalty"]

def plan(scores, df, today, now=None):
    today = pd.Timestamp(today).normalize(); A = RULES["appointment"]; B = RULES["bends"]; WO = RULES["weekly_order"]
    R = roster(); st = rep_status(df, today); reps = list(R)
    leads = pd.DataFrame(scores["leads"])
    leads["when"] = pd.to_datetime(leads.appt); leads["day"] = leads.when.dt.normalize()
    if now is not None: leads = leads[leads.when >= pd.Timestamp(now)].reset_index(drop=True)
    S = pd.DataFrame(scores["scores"]); S = S[S.guid.isin(leads.guid)]; val = S.set_index(["guid", "rep"])
    w = scores["meta"]["same_day_weight"]
    leads["min"] = leads.when.dt.hour * 60 + leads.when.dt.minute
    leads.loc[leads.appt.str.len() <= 10, "min"] = 12 * 60
    zips = df.dropna(subset=["guid"]).set_index("guid")["Job: Location Zip Code"].astype(str).str[:5]
    leads["zip"] = leads.guid.map(zips)
    leads["same_day"] = leads.days_lead_to_appt.eq(0)
    leads["week"] = leads.day - pd.to_timedelta(leads.day.dt.dayofweek, unit="D")
    office = RULES["office"]
    pairs, why_no = [], {}
    for i, l in leads.iterrows():
        dname = DAYS[l.day.dayofweek]
        for r in reps:
            info, s = R[r], st[r]; reason = None; adj = 0.0; tag = None
            slot = info["week"].get(dname)
            if s["limits"]["week_cap"] == 0: reason = s["note"] or "no leads this week"
            elif not slot or l.day.strftime("%Y-%m-%d") in info.get("days_off", []): reason = "off that day"
            elif l["min"] < hm(slot[0]): reason = "before his earliest appointment"
            elif l["min"] > hm(slot[1]): reason = "after his last appointment"
            elif slot[2] and info.get("home_zip") and l["min"] + A["minutes"] + miles(l.zip, info["home_zip"]) / A["drive_mph"] * 60 > hm(slot[2]):
                reason = "needs to be home by " + slot[2]
            elif l.comm and info["lane"] != "commercial": reason = "commercial goes to Meinardus only"
            elif l.spec and info["lane"] not in ("specialty", "commercial"): reason = "specialty goes to Francesco"
            elif not l.comm and not l.spec and info["lane"] == "commercial": reason = "Meinardus does not run regular appointments"
            elif l.spec and info["lane"] == "commercial": adj = -RULES["lanes"]["specialty_backup_penalty"]; tag = "Specialty backup"
            if reason: why_no[(l.guid, r)] = reason; continue
            v = val.loc[(l.guid, r)]
            pairs.append(dict(i=i, guid=l.guid, rep=r, day=l.day, week=l.week, min=l["min"], spec=bool(l.spec), same=bool(l.same_day),
                              value=v.close + w * v.same_day + adj, close=v.close, sd=v.same_day, tag=tag))
    P = pd.DataFrame(pairs)
    blank = lambda: [dict(guid=l.guid, appt=l.appt, rep=None, options=[], blocked={r: why_no.get((l.guid, r)) for r in reps},
                          note="Nobody free within the rules. Needs a call: move the time or day.") for l in leads.itertuples()]
    if P.empty:
        return dict(meta=dict(run=scores["meta"]["run"], appointments=len(leads), assigned=0), reps=st, plan=blank())
    n = len(P); counted = P.spec.eq(False) | is_spec_counted()
    extra, cost = [], []
    for (r, d) in sorted(set(zip(P.rep, P.day))):
        if st[r]["can_bend"]: extra.append(("bday", r, d)); cost.append(-bend_cost(st[r]["rating"]))
    for (r, wk) in sorted(set(zip(P.rep, P.week))):
        if st[r]["can_bend"]: extra.append(("bweek", r, wk)); cost.append(-bend_cost(st[r]["rating"]))
        credit = WO["minimum_credit"].get(st[r]["rating"], 0) + (WO["behind_promise_extra"] if st[r]["behind_promise"] else 0)
        extra.append(("floor", r, wk)); cost.append(credit)
    eidx = {k: n + t for t, k in enumerate(extra)}; m = n + len(extra)
    BIG = 2.0
    c = -np.r_[P.value.values + BIG + B["same_day_priority"] * P.same.values, np.array(cost)]
    rows, lo, hi = [], [], []
    def add(co, lb, ub): rows.append(co); lo.append(lb); hi.append(ub)
    for _, g in P.groupby("i"): add({j: 1 for j in g.index}, 0, 1)
    for (r, d), g in P.groupby(["rep", "day"]):
        co = {j: 1 for j in g.index}
        if ("bday", r, d) in eidx: co[eidx[("bday", r, d)]] = -B["extra_sit_per_day"]
        add(co, -np.inf, st[r]["limits"]["per_day"])
        idx = g.sort_values("min").index.tolist()
        for a in range(len(idx)):
            for b in range(a + 1, len(idx)):
                if abs(P.at[idx[a], "min"] - P.at[idx[b], "min"]) < A["min_gap_minutes"]: add({idx[a]: 1, idx[b]: 1}, 0, 1)
    for (r, wk), g in P.groupby(["rep", "week"]):
        lim = st[r]["limits"]; done = st[r]["this_week_so_far"] if wk == today - pd.Timedelta(days=today.dayofweek) else 0
        gi = [j for j in g.index if counted[j]]
        co = {j: 1 for j in gi}
        if ("bweek", r, wk) in eidx: co[eidx[("bweek", r, wk)]] = -B["extra_over_weekly_cap"]
        add(co, -np.inf, max(0, lim["week_cap"] - done))
        floor = max(0, (lim["week_min"] or 0) - done)
        co = {j: -1 for j in gi}; co[eidx[("floor", r, wk)]] = 1; add(co, -np.inf, 0)
        add({eidx[("floor", r, wk)]: 1}, 0, floor)
        if st[r]["can_bend"]:
            co = {eidx[("bweek", r, wk)]: 1}
            for (rr_, d) in [k[1:] for k in extra if k[0] == "bday" and k[1] == r and wk <= k[2] < wk + pd.Timedelta(days=7)]: co[eidx[("bday", rr_, d)]] = 1
            add(co, 0, B["max_bends_per_rep_per_week"])
    M = lil_matrix((len(rows), m))
    for k, co in enumerate(rows):
        for j, v in co.items(): M[k, j] = v
    ub = np.ones(m); ub[[eidx[e] for e in extra if e[0] == "floor"]] = 50
    res = milp(c, constraints=LinearConstraint(M.tocsr(), lo, hi), integrality=np.ones(m), bounds=Bounds(0, ub), options=dict(time_limit=120))
    x = np.round(res.x[:n]).astype(int); P["pick"] = x == 1
    bday = {k[1:]: round(res.x[eidx[k]]) for k in extra if k[0] == "bday"}
    bweek = {k[1:]: round(res.x[eidx[k]]) for k in extra if k[0] == "bweek"}
    chosen = P[P.pick]
    out = []
    for i, l in leads.iterrows():
        opts = P[P.i == i].sort_values("close", ascending=False)
        alts = [dict(rep=o.rep, close=round(o.close, 3), same_day=round(o.sd, 3)) for o in opts.itertuples()]
        blocked = {r: why_no[(l.guid, r)] for r in reps if (l.guid, r) in why_no}
        pk = chosen[chosen.i == i]
        if len(pk):
            p = pk.iloc[0]; bends = []
            if isinstance(p.tag, str): bends.append(p.tag)
            if bday.get((p.rep, p.day)): bends.append(f"{st[p.rep]['limits']['per_day'] + 1}th sit that day" + (" (keeps a same-day appointment)" if l.same_day else " (nobody else free)"))
            if bweek.get((p.rep, p.week)) and counted[p.name]: bends.append("over weekly cap" + (" (keeps a same-day appointment)" if l.same_day else " (nobody else free)"))
            if bends and st[p.rep]["rating"] in RULES["bends"]["last_resort"]["who"]: bends.append("last resort for a " + st[p.rep]["rating"] + " rep")
            best = opts.iloc[0]
            note = None if best.rep == p.rep else f"{best.rep.split()[0]} rates higher ({best.close:.0%}) but has no room or does more for the plan on other appointments"
            out.append(dict(guid=l.guid, appt=l.appt, rep=p.rep, rating=st[p.rep]["rating"], close=round(p.close, 3), same_day=round(p.sd, 3),
                            bends=bends, needs_ok=bool(bends), note=note, options=alts, blocked=blocked))
        else:
            out.append(dict(guid=l.guid, appt=l.appt, rep=None, options=alts, blocked=blocked,
                            note="Nobody free within the rules. Needs a call: move the time or day."))
    # speed: a lead that came in today but is booked for a later day. Is a fitting rep free today at that time?
    taken = chosen.groupby(["rep", "day"]).apply(lambda g: list(g["min"]), include_groups=False).to_dict()
    wk_used = chosen[counted[chosen.index]].groupby(["rep", "week"]).size().to_dict()
    wk0 = today - pd.Timedelta(days=today.dayofweek); dname = DAYS[today.dayofweek]
    for o, (_, l) in zip(out, leads.iterrows()):
        if pd.isna(l.days_lead_to_appt) or l.days_lead_to_appt < 1: continue
        if l.day - pd.Timedelta(days=int(l.days_lead_to_appt)) != today: continue
        for r in sorted(reps, key=lambda r: -(val.loc[(l.guid, r)].close if (l.guid, r) in val.index else 0)):
            info, s_ = R[r], st[r]; slot = info["week"].get(dname)
            if not slot or s_["limits"]["week_cap"] == 0 or today.strftime("%Y-%m-%d") in info.get("days_off", []): continue
            if l["min"] < hm(slot[0]) or l["min"] > hm(slot[1]) or (now is not None and pd.Timestamp(now).hour * 60 + pd.Timestamp(now).minute > l["min"] - 60): continue
            if (l.comm and info["lane"] != "commercial") or (l.spec and info["lane"] not in ("specialty", "commercial")) or (not l.comm and not l.spec and info["lane"] == "commercial"): continue
            day_list = taken.get((r, today), [])
            if any(abs(t - l["min"]) < A["min_gap_minutes"] for t in day_list): continue
            if len(day_list) >= s_["limits"]["per_day"]: continue
            if s_["this_week_so_far"] + wk_used.get((r, wk0), 0) >= s_["limits"]["week_cap"]: continue
            o["sooner"] = dict(day=today.strftime("%Y-%m-%d"), rep=r, note="Lead came in today. Could be seen today at the same time."); break
    a = [o for o in out if o["rep"]]
    meta = dict(run=scores["meta"]["run"], appointments=len(out), assigned=len(a), nobody_free=len(out) - len(a),
                bends=sum(1 for o in a if o["bends"]), expected_closes=round(float(sum(o["close"] for o in a)), 1),
                expected_same_day=round(float(sum(o["same_day"] for o in a)), 1), solver=res.message)
    return dict(meta=meta, reps=st, plan=out)

def main(out, path, today=None):
    live = today is None
    today = pd.Timestamp(today or datetime.now()).normalize()
    scores = json.loads((Path(out) / "scores.json").read_text())
    df = E.load(path)
    p = plan(scores, df, today, now=datetime.now() if live else None)
    json.dump(p, open(Path(out) / "plan.json", "w"), indent=1, default=str)
    log = pd.DataFrame([dict(run_date=today.strftime("%Y-%m-%d"), guid=o["guid"], appt=o["appt"], rep=o["rep"] or "",
                             close=o.get("close", ""), same_day=o.get("same_day", ""), bends="; ".join(o.get("bends", []))) for o in p["plan"]])
    f = E.MEM / "plans.csv"
    if f.exists():
        old = pd.read_csv(f, dtype=str); log = pd.concat([old[old.run_date != today.strftime("%Y-%m-%d")], log.astype(str)])
    log.to_csv(f, index=False)
    print(p["meta"])
    for r, s in p["reps"].items(): print(" ", r, s["rating"], s["close"], f"({s['sits']} sits, rolling {s['window']})", s["limits"], s["note"] or "", "promise avg", s["promise_avg"])

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
