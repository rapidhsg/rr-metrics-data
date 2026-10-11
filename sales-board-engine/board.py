"""Build board.json for the dashboard from the engine's scores.json + plan.json and the job export.
One card per upcoming appointment: who the engine picked, every rep's odds, why, and what blocks each rep.
Customer name only. Phone numbers and emails are stripped from notes.
Usage: python board.py <out dir> <job export csv> [status.json, default: next to the csv]   (reads <out>/scores.json and <out>/plan.json, writes <out>/board.json)"""
import json, re, sys
from pathlib import Path
import pandas as pd
import engine as E

PHONE = re.compile(r"(\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def clean(t, n=280):
    if not isinstance(t, str) or not t.strip(): return None
    t = EMAIL.sub("[email]", PHONE.sub("[phone]", " ".join(t.split())))
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def txt(v):
    return None if pd.isna(v) or str(v).strip() in ("", "nan") else " ".join(str(v).split())


LABEL = {"Rep": "Strong rep overall", "has_notes": "Has lead notes", "Newer rep (still proving out)": "Newer rep, still proving out"}


NOTE = {"leak": "Notes mention a leak", "noleak": "Notes say no leak", "storm": "Notes mention storm damage", "firstcall": "First call to us",
        "referral": "Notes mention a referral", "skylight": "Notes mention a skylight"}
DISPLAY = {"Querlim Franco": ("Franco Querlim", "Franco"), "Francesco Ambrosio": ("Francesco", "Francesco"),
           "Michael Dietrich": ("Mike Dietrich", "Dietrich"), "Joseph Young": ("Joe Young", "Joe"),
           "Steve Burns": ("Steve Burns", "Steve"), "Michael Meinardus": ("Mike Meinardus", "Meinardus")}
DAYS = "Mon Tue Wed Thu Fri Sat Sun".split()


def label(s):
    s = LABEL.get(s, s)
    if s.startswith("Note: "): s = NOTE.get(s[6:], "Notes mention " + s[6:])
    elif s.startswith("Weekday: ") and s[9:].isdigit(): s = "Day of week: " + DAYS[int(s[9:]) % 7]
    elif s.startswith("Area: "): s = "Area: " + s[6:] + "xx zips"
    elif s.startswith("Rep fit: "): s = "Rep fit on " + s[9:]
    return s[0].upper() + s[1:] if s else s


def main(out, path, status=None):
    out = Path(out)
    S = json.loads((out / "scores.json").read_text())
    P = json.loads((out / "plan.json").read_text())
    rules = json.loads((Path(__file__).parent / "assignment_rules.json").read_text())
    df = E.load(path).set_index("guid")
    lead = {l["guid"]: l for l in S["leads"]}
    by = {}
    for s in S["scores"]: by.setdefault(s["guid"], {})[s["rep"]] = s
    cards = []
    for p in P["plan"]:
        g = p["guid"]; r = df.loc[g] if g in df.index else None
        if isinstance(r, pd.DataFrame): r = r.iloc[0]
        L = lead.get(g, {}); sc = by.get(g, {}); pick = p.get("rep")
        odds = {k: dict(close=v["close"], same_day=v["same_day"]) for k, v in sc.items()}
        free = [v["close"] for k, v in sc.items() if k != pick and k not in (p.get("blocked") or {})]
        why = sc.get(pick, {}) if pick else {}
        tag = "commercial" if L.get("comm") else "specialty" if L.get("spec") else None
        cards.append(dict(
            id=g, url=f"https://my.acculynx.com/jobs/{g}", appt=p["appt"],
            name=txt(r["Primary Contact: Name"]) if r is not None else None,
            town=(txt(r["Job: Location City"]) or "").title() or None if r is not None else None,
            zip=(txt(r["Job: Location Zip Code"]) or "")[:5] or None if r is not None else None,
            rr=txt(r["Job Number"]) if r is not None else None,
            source=txt(r["Sub Lead Source"]) if r is not None else None,
            parent=txt(r["Parent Lead Source"]) if r is not None else None,
            hot=txt(r["Appointment Rating"]) if r is not None else None,
            set_by=txt(r["Appointment Set By"]) if r is not None else None,
            in_acculynx=(lambda v: v if v in rules["roster"] else None)(txt(r["Primary Salesperson"])) if r is not None else None,
            notes=clean(r["INITIAL LEAD NOTES"]) if r is not None else None,
            more_notes=clean(r["ADDITIONAL LEAD NOTES"]) if r is not None else None,
            lane=tag, ltype=L.get("ltype"), booked_today=L.get("days_lead_to_appt") == 0, days_out=L.get("days_lead_to_appt"),
            lead_close=L.get("lead_close"),
            pick=pick, close=p.get("close"), same_day=p.get("same_day"),
            lift=round(p["close"] - max(free), 4) if pick and free else None,
            needs_ok=bool(p.get("needs_ok")), bends=p.get("bends") or [], note=p.get("note"),
            blocked=p.get("blocked") or {}, odds=odds,
            up=[label(u[0]) for u in why.get("up", [])][:3], down=[label(d[0]) for d in why.get("down", [])][:3]))
    reps = []
    for name, st in P["reps"].items():
        ro = rules["roster"].get(name, {})
        if not ro.get("active", True): continue
        disp, short = DISPLAY.get(name, (name, name.split()[0]))
        if ro.get("display"): disp = ro["display"]
        reps.append(dict(name=name, display=disp, short=short, rating=st["rating"], close=st["close"], sits=st["sits"], window=st["window"],
                         day=st["day"], limits={k: v for k, v in st["limits"].items() if not k.startswith("_")},
                         note=st.get("note"), this_week=st["this_week_so_far"], promise=st.get("promise"), availability=st.get("availability"), promise_avg=st.get("promise_avg"), lane=ro.get("lane", "regular"),
                         week=ro.get("week", {}), home_zip=ro.get("home_zip"), days_off=ro.get("days_off", [])))
    full2short = {r["name"]: r["short"] for r in reps}
    for c in cards:
        if c["note"]:
            for full, sh in full2short.items(): c["note"] = c["note"].replace(full, sh)
    today = pd.Timestamp(P["meta"]["run"][:10])
    rr = E.rr
    # zip heat: certified close rate per zip, last 12 months
    s0, e0 = rr.rolling(today, 365); m = rr.masks(df.reset_index(), s0, e0)
    d0 = df.reset_index(); z5 = d0["Job: Location Zip Code"].astype(str).str[:5]
    sits = m["close_sits_company"]; sold = m["close_sold_company"]
    zips = {}
    for z, g in d0[sits].groupby(z5[sits]):
        if len(z) == 5 and z.isdigit():
            zips[z] = dict(n=int(len(g)), sold=int(sold[g.index].sum()), city=(g["Job: Location City"].dropna().astype(str).str.title().mode().iloc[0] if g["Job: Location City"].notna().any() else None))
    # results: weekly team close rate and same-day rate (certified team close sits), last 20 weeks
    wk = today - pd.Timedelta(days=today.dayofweek)
    weeks = []
    for i in range(20, 0, -1):
        ws = wk - pd.Timedelta(days=7 * i); we = ws + pd.Timedelta(days=6)
        mm = rr.masks(d0, ws, we); t = mm["close_sits_team"]; sd = t & (d0["Approved Milestone Date"].dt.normalize() == d0["Initial Appointment Date"].dt.normalize())
        weeks.append(dict(week=ws.strftime("%Y-%m-%d"), sits=int(t.sum()), sold=int(mm["close_sold_team"].sum()), same_day=int(sd.sum())))
    r30 = rr.metrics(d0, *rr.rolling(today, 30)); r90 = rr.metrics(d0, *rr.rolling(today, 90))
    s9, e9 = rr.rolling(today, 90); m9 = rr.masks(d0, s9, e9)
    board = []
    for r in reps:
        k = d0["Primary Salesperson"] == r["name"]; t = m9["close_sits_team"] & k
        board.append(dict(name=r["name"], sits=int(t.sum()), sold=int((m9["close_sold_team"] & k).sum()),
                          sales=round(float(d0.loc[m9["sales"] & k, "Contract Amount"].sum()), 0)))
    results = dict(weeks=weeks, engine_start=rules.get("engine_start", "2026-10-12"),
                   r30=dict(sits=r30["close_sits_team"], sold=r30["close_sold_team"]),
                   r90=dict(sits=r90["close_sits_team"], sold=r90["close_sold_team"], sales=r90["sales"]), reps90=board)
    # average contract per sale, last 12 months of certified sold sits, by lead type and same day vs later
    sold = m["close_sold_company"] & (d0["Contract Amount"] > 0)
    xs = E.features(d0[sold]); xs.index = d0[sold].index
    sd0 = (d0.loc[sold, "Approved Milestone Date"].dt.normalize() == d0.loc[sold, "Initial Appointment Date"].dt.normalize())
    amt = d0.loc[sold, "Contract Amount"]
    tickets = {"all": dict(any=round(float(amt.mean())), same_day=round(float(amt[sd0].mean())), n=int(len(amt)))}
    for lt, g in amt.groupby(xs["ltype"]):
        if len(g) >= 15:
            s_ = g[sd0[g.index]]
            tickets[lt] = dict(any=round(float(g.mean())), same_day=round(float(s_.mean())) if len(s_) >= 10 else round(float(g.mean())), n=int(len(g)))
    # forecast: how many more appointments usually get booked for each upcoming day between today and that day
    FC = rules.get("forecast", {}); wins = FC.get("windows_days", [30, 60, 90])
    ma = rr.masks(d0, today - pd.Timedelta(days=max(wins) + 120), today)["appointments"]
    ap = d0[ma & d0["Initial Appointment Date"].notna()]
    ia = ap["Initial Appointment Date"].dt.normalize(); lt = (ia - ap["Prospect Milestone Date"].dt.normalize()).dt.days
    forecast = {}
    for i in range(0, 15):
        D = today + pd.Timedelta(days=i); f = {}
        for w in wins:
            days = [today - pd.Timedelta(days=k) for k in range(1, w + 1) if (today - pd.Timedelta(days=k)).dayofweek == D.dayofweek]
            more = [int(((ia == h) & lt.between(0, i)).sum()) for h in days]
            total = [int((ia == h).sum()) for h in days]
            f[str(w)] = dict(more=round(sum(more) / len(more), 1) if more else 0, typical=round(sum(total) / len(total), 1) if total else 0)
        forecast[D.strftime("%Y-%m-%d")] = f
    roster_out = {k: v for k, v in rules["roster"].items() if not k.startswith("_")}
    meta = dict(P["meta"]); meta.pop("solver", None)
    meta.update(data_as_of=S["meta"]["run"], sits_used=S["meta"]["sits_used"])
    st = Path(status) if status else Path(path).with_name("status.json")
    if st.exists():   # when AccuLynx ran the report and when GitHub pulled it (data branch status.json)
        j = json.loads(st.read_text()).get("job_export_raw", {})
        meta.update(acculynx_run=j.get("runDate"), acculynx_slot=j.get("schedule"), pulled_at=j.get("pulledAt"))
    json.dump(dict(meta=meta, office=rules["office"], appointment=rules["appointment"], reps=reps, roster=roster_out,
                   cards=sorted(cards, key=lambda c: c["appt"]), zips=zips, results=results, tickets=tickets, forecast=forecast, forecast_show=str(FC.get('show', 60))),
              open(out / "board.json", "w"), separators=(",", ":"), allow_nan=False)
    print(f"board.json: {len(cards)} cards, {len(reps)} reps")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
