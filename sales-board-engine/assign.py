"""Hands out upcoming appointments to reps: the plan with the most expected closes that fits the rules in
settings.json -> assignment. Solved as one optimization over every upcoming day at once (so weekly limits work).
Value of a pick = close chance + same-day weight x same-day chance, plus lane bonuses, minus rule-bend penalties.
Usage: python assign.py <out dir>   (reads <out dir>/scores.json from run.py, writes <out dir>/plan.json)"""
import json, math, sys
from pathlib import Path
from datetime import datetime
import numpy as np, pandas as pd
from scipy.optimize import milp, LinearConstraint, Bounds
from scipy.sparse import lil_matrix
import engine as E

A = E.CFG["assignment"]
ZC = json.loads((E.HERE / "zip_centers.json").read_text())

def miles(z1, z2):
    if z1 not in ZC or z2 not in ZC: return 15.0
    (x1, y1), (x2, y2) = ZC[z1], ZC[z2]
    return math.hypot((x1 - x2) * 69 * math.cos(math.radians(40.8)), (y1 - y2) * 69)

def hm(t): return None if not t else int(t[:2]) * 60 + int(t[3:5])

def plan(scores, df, today, week_sits=None, now=None):
    today = pd.Timestamp(today).normalize()
    leads = pd.DataFrame(scores["leads"]); S = pd.DataFrame(scores["scores"]); S = S[S.guid.isin(leads.guid)]
    w = scores["meta"]["same_day_weight"]
    leads["when"] = pd.to_datetime(leads.appt); leads["day"] = leads.when.dt.normalize()
    if now is not None: leads = leads[leads.when >= pd.Timestamp(now)].reset_index(drop=True)   # skip appointments already started
    leads["min"] = leads.when.dt.hour * 60 + leads.when.dt.minute
    leads.loc[leads.appt.str.len() <= 10, "min"] = 12 * 60
    zips = df.set_index("guid")["Job: Location Zip Code"].astype(str).str[:5]
    leads["zip"] = leads.guid.map(zips)
    reps = list(A["reps"]); R = A["reps"]
    # strong closer = his average close chance on these leads is at or above the lead's average-rep chance
    avg = S.groupby("rep").close.mean(); team = avg[[r for r in reps if not R[r].get("lane_rep")]].mean()
    strong = {r: bool(avg.get(r, 0) >= team) for r in reps}
    first = df.groupby("Primary Salesperson")["Initial Appointment Date"].min()
    start = {r: min([d for d in [pd.Timestamp(R[r]["hired"]) if R[r]["hired"] else None, first.get(r)] if d is not None and pd.notna(d)], default=today) for r in reps}
    newer = {r: (today - start[r]).days < A["weekly_capacity"]["newer_days"] and not R[r].get("lane_rep") for r in reps}
    if week_sits is None: week_sits = {}
    val = S.set_index(["guid", "rep"])
    pairs, why_no = [], {}
    for i, l in leads.iterrows():
        for r in reps:
            rr = R[r]; dow = l.day.dayofweek; reason = None
            if dow not in rr["days"] or l.day.strftime("%Y-%m-%d") in A.get("days_off", {}).get(r, []): reason = "off that day"
            elif hm(rr["start"]) and l["min"] < hm(rr["start"]): reason = "before his start time"
            elif hm(rr["last"]) and l["min"] > hm(rr["last"]): reason = "after his last appointment time"
            elif rr["home_by"] and rr["home_zip"]:
                drive = miles(l.zip, rr["home_zip"]) / A["drive_mph"] * 60
                if l["min"] + A["appointment_minutes"] + drive > hm(rr["home_by"]): reason = "needs to be home by " + rr["home_by"]
            adj, tag = 0.0, None
            if reason is None:
                if l.spec:
                    lanes = A["lanes"]["specialty"]["reps"]
                    if r not in lanes: reason = "specialty roofs go to Francesco"
                    else: adj = lanes[r]; tag = "Specialty backup" if adj < 0 else None
                elif l.comm:
                    lanes = A["lanes"]["commercial"]["reps"]
                    if r not in lanes: reason = "commercial goes to Meinardus or Dietrich"
                    else: adj = lanes[r]; tag = "Commercial backup" if adj < 0 else None
                elif rr.get("lane_rep"):
                    adj = A["lanes"]["meinardus_other_work"]; tag = "Meinardus overflow"
            if reason: why_no[(l.guid, r)] = reason; continue
            v = val.loc[(l.guid, r)]
            pairs.append(dict(i=i, guid=l.guid, rep=r, day=l.day, min=l["min"], value=v.close + w * v.same_day + adj,
                              close=v.close, same=v.same_day, tag=tag))
    P = pd.DataFrame(pairs)
    if P.empty:
        return dict(meta=dict(run=scores["meta"]["run"], solver="nothing to assign", appointments=len(leads), assigned=0, expected_closes=0, expected_same_day=0,
                              strong_closers=[], newer_reps=[]),
                    plan=[dict(guid=l.guid, appt=l.appt, rep=None, options=[], blocked={r: why_no.get((l.guid, r)) for r in reps},
                               note="Nobody free within the rules. Needs a call: move the time or day, or bend a rule.") for l in leads.itertuples()])
    n = len(P)
    # extra variables: per rep-day 4th and 5th sit, per newer rep-week over cap, per rep-week floor credit
    P["week"] = P.day - pd.to_timedelta(P.day.dt.dayofweek, unit="D")
    rd = sorted(set(zip(P.rep, P.day))); rw = sorted(set(zip(P.rep, P.week)))
    ov = A["overbooking"]
    extra, cost = [], []
    for r, d in rd:
        extra.append(("4th", r, d)); cost.append(-(ov["fourth_sit_strong_closer"] if strong[r] else ov["fourth_sit_anyone"]))
        extra.append(("5th", r, d)); cost.append(-ov["fifth_sit_strong_closer"] if strong[r] else -9.0)
    for r, wk in rw:
        extra.append(("overcap", r, wk)); cost.append(-ov["newer_rep_past_weekly_cap"] if newer[r] and not strong[r] else 0.0)
        extra.append(("floor", r, wk)); cost.append(A["capacity_floor_bonus"])
    m = n + len(extra)
    BIG = 2.0   # assigning an appointment beats leaving it unassigned
    c = -np.r_[P.value.values + BIG, np.array(cost)]
    rows, lo, hi = [], [], []
    M = lil_matrix((0, m))
    def add(coefs, lb, ub):
        rows.append(coefs); lo.append(lb); hi.append(ub)
    # each appointment at most one rep
    for i, g in P.groupby("i"): add({j: 1 for j in g.index}, 0, 1)
    eidx = {k: n + t for t, k in enumerate(extra)}
    for (r, d), g in P.groupby(["rep", "day"]):
        # sits per day <= 3 + 4th + 5th
        co = {j: 1 for j in g.index}; co[eidx[("4th", r, d)]] = -1; co[eidx[("5th", r, d)]] = -1
        add(co, -np.inf, A["sits_per_day"])
        add({eidx[("5th", r, d)]: 1, eidx[("4th", r, d)]: -1}, -np.inf, 0)
        # time conflicts: two stops closer than the minimum gap
        idx = g.sort_values("min").index.tolist()
        for a in range(len(idx)):
            for b in range(a + 1, len(idx)):
                if abs(P.at[idx[a], "min"] - P.at[idx[b], "min"]) < A["min_gap_minutes"]: add({idx[a]: 1, idx[b]: 1}, 0, 1)
    for (r, wk), g in P.groupby(["rep", "week"]):
        done = week_sits.get((r, wk), 0)
        cap = A["weekly_capacity"]["newer"] if newer[r] else A["weekly_capacity"]["tenured"]
        if newer[r] and not strong[r]:   # newer reps capped at 7 unless strong; going over costs a penalty
            co = {j: 1 for j in g.index}; co[eidx[("overcap", r, wk)]] = -50
            add(co, -np.inf, max(0, cap - done))
        floor = 0 if R[r].get("lane_rep") else max(0, cap - done)
        co = {j: -1 for j in g.index}; co[eidx[("floor", r, wk)]] = 1
        add(co, -np.inf, 0)                           # floor credit <= sits given
        add({eidx[("floor", r, wk)]: 1}, 0, floor)    # and <= the sits still needed to reach the floor
    Mx = lil_matrix((len(rows), m))
    for k, co in enumerate(rows):
        for j, v in co.items(): Mx[k, j] = v
    integ = np.ones(m); integ[[eidx[e] for e in extra if e[0] in ("floor", "overcap")]] = 1
    ub = np.ones(m); ub[[eidx[e] for e in extra if e[0] in ("floor", "overcap")]] = 50
    res = milp(c, constraints=LinearConstraint(Mx.tocsr(), lo, hi), integrality=integ, bounds=Bounds(0, ub),
               options=dict(time_limit=120))
    x = np.round(res.x[:n]).astype(int)
    P["pick"] = x == 1
    out = []
    picked = P[P.pick].set_index("guid")
    day_count = P[P.pick].groupby(["rep", "day"]).size()
    for i, l in leads.iterrows():
        opts = P[P.i == i].sort_values("value", ascending=False)
        alts = [dict(rep=o.rep, close=round(o.close, 3), same_day=round(o.same, 3), value=round(o.value, 3)) for o in opts.itertuples()]
        blocked = {r: why_no[(l.guid, r)] for r in reps if (l.guid, r) in why_no}
        if l.guid in picked.index:
            p = picked.loc[l.guid]; bends = []
            if isinstance(p.tag, str): bends.append(p.tag)
            k = day_count.get((p.rep, l.day), 0)
            if k > A["sits_per_day"]: bends.append(f"{k} sits that day")
            best = opts.iloc[0]
            note = None if best.rep == p.rep else f"{E.CFG['board_reps'][best.rep]} rates higher ({best.close:.0%}) but the plan does better with him on other appointments or he has no room"
            out.append(dict(guid=l.guid, appt=l.appt, rep=p.rep, close=round(p.close, 3), same_day=round(p.same, 3),
                            value=round(p.value, 3), bends=bends, note=note, options=alts, blocked=blocked))
        else:
            out.append(dict(guid=l.guid, appt=l.appt, rep=None, options=alts, blocked=blocked,
                            note="Nobody free within the rules. Needs a call: move the time or day, or bend a rule."))
    exp_close = sum(o["close"] for o in out if o["rep"]); exp_same = sum(o["same_day"] for o in out if o["rep"])
    return dict(meta=dict(run=scores["meta"]["run"], solver=res.message, appointments=len(out), assigned=sum(1 for o in out if o["rep"]),
                          expected_closes=round(float(exp_close), 1), expected_same_day=round(float(exp_same), 1), strong_closers=[r for r in reps if strong[r]],
                          newer_reps=[r for r in reps if newer[r]]), plan=out)

def sits_this_week(df, today):
    today = pd.Timestamp(today).normalize(); wk0 = today - pd.Timedelta(days=today.dayofweek)
    m = (df["Initial Appointment Date"] >= wk0) & (df["Initial Appointment Date"] < today)
    return {(r, wk0): int(n) for r, n in df[m].groupby("Primary Salesperson").size().items()}

def main(out, path, today=None):
    today = pd.Timestamp(today or datetime.now()).normalize()
    scores = json.loads((Path(out) / "scores.json").read_text())
    df = E.load(path)
    p = plan(scores, df, today, sits_this_week(df, today), now=datetime.now() if len(sys.argv) <= 3 else None)
    json.dump(p, open(Path(out) / "plan.json", "w"), indent=1)
    log = pd.DataFrame([dict(run_date=today.strftime("%Y-%m-%d"), guid=o["guid"], appt=o["appt"], rep=o["rep"] or "",
                             close=o.get("close", ""), same_day=o.get("same_day", "")) for o in p["plan"]])
    f = E.MEM / "plans.csv"
    if f.exists():
        old = pd.read_csv(f, dtype=str); log = pd.concat([old[old.run_date != today.strftime("%Y-%m-%d")], log.astype(str)])
    log.to_csv(f, index=False)
    print(p["meta"])

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
