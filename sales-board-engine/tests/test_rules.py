"""Regression test for the assignment rules. Runs the plan on the latest data and checks every hard rule holds.
Run after any change to assign.py or assignment_rules.json, and in every scheduled run. Exit code 1 = a rule broke.
Usage: python tests/test_rules.py <job export csv> <out dir with scores.json and plan.json>"""
import json, sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
import assign as A

def hm(t): h, m = map(int, t.split(":")); return h * 60 + m

def main(path, out):
    plan = json.loads((Path(out) / "plan.json").read_text())
    scores = json.loads((Path(out) / "scores.json").read_text())
    lead = {l["guid"]: l for l in scores["leads"]}
    R = A.roster(); st = plan["reps"]; gap = A.RULES["appointment"]["min_gap_minutes"]
    bad = []; per_day = defaultdict(list)
    for p in plan["plan"]:
        r = p.get("rep")
        if not r: continue
        L = lead[p["guid"]]; when = pd.Timestamp(p["appt"]); day = when.strftime("%Y-%m-%d"); m = when.hour * 60 + when.minute
        info = R[r]; slot = A.slot_for(info, when.normalize())
        per_day[(r, day)].append(m)
        if not slot: bad.append(f"{r} not working {day} (schedule, day off, or Availability tab)")
        elif not p.get("bends"):
            if m < hm(slot[0]) or m > hm(slot[1]): bad.append(f"{r} outside hours {p['appt']}")
        if L.get("comm") and info["lane"] != "commercial": bad.append(f"commercial to {r}")
        if not L.get("comm") and not L.get("spec") and info["lane"] == "commercial": bad.append(f"regular appointment to {r}")
        if L.get("spec") and info["lane"] == "regular": bad.append(f"specialty to {r}")
    for (r, day), ms in per_day.items():
        lim = st[r]["limits"]["per_day"]
        if len(ms) > lim + 1: bad.append(f"{r} has {len(ms)} on {day} (limit {lim}, at most one bend)")
        if len(ms) > 4: bad.append(f"{r} has a 5th sit on {day}")
        ms = sorted(ms)
        for a, b in zip(ms, ms[1:]):
            if b - a < gap: bad.append(f"{r} two appointments under {gap} min apart on {day}")
    hot = A.RULES.get("hot", {})
    for r, s in st.items():
        if s.get("note", "") and s["note"].startswith("Hot streak") and s["rating"] != hot.get("rated_as"): bad.append(f"{r} hot but rated {s['rating']}")
        if s.get("promise") is not None and s["promise"] > A.RULES["yearly_promise"]["per_week_average"] + 1e-9: bad.append(f"{r} promise above 7")
    print("rules OK" if not bad else "RULES BROKEN:\n  " + "\n  ".join(bad))
    sys.exit(1 if bad else 0)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
