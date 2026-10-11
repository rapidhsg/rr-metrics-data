"""The assignment logic improving on its own. Run weekly after selftest.py.
Reads memory/outcomes.csv (every finished sit, which experiment arm its day was on, and how good the lead was),
compares champion days with challenger days for the running experiment, and keeps the winner when the gap is real.
Then starts the next experiment from the queue. Writes assignment_rules.json, memory/experiments.csv and the learning log.
Usage: python learn.py [today]"""
import json, math, sys
from datetime import datetime
from pathlib import Path
import pandas as pd
import engine as E

RULES_PATH = Path(__file__).parent / "assignment_rules.json"


def main(today=None):
    today = pd.Timestamp(today or datetime.now()).normalize()
    R = json.loads(RULES_PATH.read_text()); L = R["learning"]; ex = L.get("experiment") or {}
    log = []
    if not ex.get("active"):
        nxt = start_next(L, today); log.append(nxt); save(R, log, today); return
    o = E.MEM / "outcomes.csv"
    if not o.exists(): print("no outcomes yet"); return
    d = pd.read_csv(o)
    d = d[(d.sat == True) & (d.appt.str[:10] >= ex["started"]) & d.lead_base.notna()]
    d["lift"] = d.sold.astype(float) - d.lead_base          # closed vs what the lead alone predicted
    a, b = d[d.arm == "champion"], d[d.arm == "challenger"]
    n_a, n_b = len(a), len(b)
    weeks = (today - pd.Timestamp(ex["started"])).days / 7
    line = f"Experiment {ex['dial']} {ex['champion']} vs {ex['challenger']}: {n_a} champion sits, {n_b} challenger sits"
    if n_a < L["min_sits_per_side"] or n_b < L["min_sits_per_side"]:
        if weeks >= L["max_weeks"]:
            log.append(line + f". Not enough sits after {weeks:.0f} weeks; keeping {ex['champion']} and moving on.")
            record(ex, "no decision", 0, 0, n_a, n_b, today); L["experiment"] = {"active": False}; log.append(start_next(L, today))
        else:
            log.append(line + f". Waiting for {L['min_sits_per_side']} on each side.")
        save(R, log, today); return
    gain = (b.lift.mean() - a.lift.mean()) * 100
    se = math.sqrt(b.lift.var() / n_b + a.lift.var() / n_a) * 100 or 1e-9
    z = gain / se
    line += f". Challenger closed {gain:+.1f} points vs champion after adjusting for lead quality (z = {z:.2f})."
    if gain >= L["min_gain_points"] and z >= L["confidence_z"]:
        if L.get("auto_promote", True):
            L["dials"][ex["dial"]]["value"] = ex["challenger"]; verdict = "promoted"
            log.append(line + f" PROMOTED: {ex['dial']} is now {ex['challenger']}.")
        else:
            verdict = "proposed"; log.append(line + f" PROPOSED for approval: set {ex['dial']} to {ex['challenger']}.")
    elif gain <= -L["min_gain_points"] and z <= -L["confidence_z"]:
        verdict = "rejected"; log.append(line + f" REJECTED: keeping {ex['champion']}.")
    elif weeks >= L["max_weeks"]:
        verdict = "no clear winner"; log.append(line + f" No clear winner after {weeks:.0f} weeks; keeping {ex['champion']}.")
    else:
        log.append(line + " Not decided yet; keeps running."); save(R, log, today); return
    record(ex, verdict, gain, z, n_a, n_b, today)
    L["experiment"] = {"active": False}; log.append(start_next(L, today))
    save(R, log, today)


def start_next(L, today):
    tried = set()
    p = E.MEM / "experiments.csv"
    if p.exists(): tried = set(pd.read_csv(p).apply(lambda r: f"{r.dial}={r.challenger}", axis=1))
    for name in L["queue"]:
        dv = L["dials"][name]
        for c in dv.get("try", []):
            lo, hi = dv["range"]
            if c != dv["value"] and lo <= c <= hi and f"{name}={c}" not in tried:
                L["experiment"] = dict(active=True, dial=name, champion=dv["value"], challenger=c,
                                       challenger_parity=int(today.toordinal() % 2 == 0), started=(today + pd.Timedelta(days=1)).strftime("%Y-%m-%d"))
                return f"Next experiment: {name} {dv['value']} vs {c}, on alternating days from {L['experiment']['started']}."
    L["experiment"] = {"active": False}
    return "Every queued idea has been tried. Add new ones to learning.dials.*.try to keep improving."


def record(ex, verdict, gain, z, n_a, n_b, today):
    p = E.MEM / "experiments.csv"
    row = pd.DataFrame([dict(decided=today.strftime("%Y-%m-%d"), dial=ex["dial"], champion=ex["champion"], challenger=ex["challenger"],
                             started=ex["started"], champion_sits=n_a, challenger_sits=n_b, gain_points=round(gain, 2), z=round(z, 2), verdict=verdict)])
    (pd.concat([pd.read_csv(p), row]) if p.exists() else row).to_csv(p, index=False)


def save(R, log, today):
    RULES_PATH.write_text(json.dumps(R, indent=2) + "\n")
    with open(E.MEM / "learning_log.md", "a") as f:
        f.write(f"\n## {today:%Y-%m-%d} assignment experiments\n" + "".join(f"- {x}\n" for x in log))
    print("\n".join(log))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
