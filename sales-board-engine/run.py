"""Score every upcoming appointment for every board rep. Run after each AccuLynx pull.
Writes <out>/scores.json and <out>/plan.json (the recommended assignment) for the board and appends to memory/predictions.csv (the engine's record of what it predicted,
used later to check itself against results).
Usage: python run.py <path to job_export_raw_latest.csv> <out dir> [today]"""
import json, sys
from datetime import datetime
from pathlib import Path
import numpy as np, pandas as pd
import engine as E

def main(path, out, today=None):
    today_arg = today
    now = pd.Timestamp(today or datetime.now())
    today = now.normalize()
    df = E.load(path)
    t = E.tuned()
    S, x = E.training(df, today)
    mc, ms = E.fit_both(x, today, t)
    w = t.get("same_day_weight")
    if w is None: w = E.same_day_value(S)["weight"]
    corr = t.get("correction", {}) or {}
    F = df[(df["Initial Appointment Date"] >= today) & (df["Current Milestone"] == "Prospect")]
    xf = E.features(F)
    hist, n = E.rep_experience(df)
    sits_so_far = hist.groupby("Primary Salesperson").size()
    import assign
    reps = list(assign.roster())
    rows, leads = [], []
    shift = lambda p, c: 1 / (1 + np.exp(-(np.log(p / (1 - p)) + c))) if c else p
    for rep in reps:
        xr = xf.copy(); xr["rep"] = rep; xr["rep_n"] = float(sits_so_far.get(rep, 0))
        pc = shift(mc.predict(xr), corr.get("close", 0)); ps = shift(ms.predict(xr), corr.get("same_day", 0))
        why = mc.reasons(xr)
        for i, g in enumerate(xr.guid):
            rows.append(dict(guid=g, rep=rep, close=round(float(pc[i]), 4), same_day=round(float(ps[i]), 4),
                             score=round(float(pc[i] + w * ps[i]), 4), up=why[i]["up"], down=why[i]["down"]))
    # lead quality with an average rep (rep layer switched to the team)
    xa = xf.copy(); xa["rep"] = "none"; xa["rep_n"] = 999
    base_c, base_s = mc.predict(xa), ms.predict(xa)
    for i, (idx, r) in enumerate(xf.iterrows()):
        leads.append(dict(guid=r.guid, appt=F.loc[idx, "appt_time"].strftime("%Y-%m-%dT%H:%M") if pd.notna(F.loc[idx, "appt_time"]) else r.date.strftime("%Y-%m-%d"),
                          lead_close=round(float(base_c[i]), 4), lead_same_day=round(float(base_s[i]), 4),
                          days_lead_to_appt=None if pd.isna(r.l2a) else int(r.l2a), ltype=r.ltype, spec=bool(r.spec), comm=bool(r.comm)))
    Path(out).mkdir(parents=True, exist_ok=True)
    meta = dict(run=now.strftime("%Y-%m-%d %H:%M"), window_days=E.CFG["data_window_days"], sits_used=int(len(x)),
                tuning={k: t[k] for k in ("half_life_days", "shrink_C")}, same_day_weight=w, correction=corr)
    json.dump(dict(meta=meta, leads=leads, scores=rows), open(Path(out) / "scores.json", "w"), separators=(",", ":"))
    log = pd.DataFrame([dict(run_date=today.strftime("%Y-%m-%d"), appt_date=next(l["appt"][:10] for l in leads if l["guid"] == r["guid"]),
                             guid=r["guid"], rep=r["rep"], close=r["close"], same_day=r["same_day"]) for r in rows])
    p = E.MEM / "predictions.csv"
    if p.exists():
        old = pd.read_csv(p, dtype=str)
        log = pd.concat([old[old.run_date != today.strftime("%Y-%m-%d")], log.astype(str)])
    log.to_csv(p, index=False)
    print(f"scored {len(leads)} appointments x {len(reps)} reps; sits used {len(x)}; same-day weight {w}")
    assign.main(out, path, today=today_arg)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
