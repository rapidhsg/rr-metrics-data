"""Copy the dashboard's Reps tab (roster docs saved by the board) into assignment_rules.json before the engine runs.
The dashboard owns the roster: hours, days off, capacity, lane, active. Everything else in the rules file is untouched.
Usage: python sync_roster.py <folder of roster/*.json docs exported from the board's database>"""
import json, sys
from pathlib import Path

FIELDS = ("active", "lane", "start_date", "home_zip", "week", "days_off", "capacity", "display")


def main(folder):
    p = Path(__file__).parent / "assignment_rules.json"
    rules = json.loads(p.read_text())
    ro = rules["roster"]; changed = []
    for f in sorted(Path(folder).glob("*.json")):
        doc = json.loads(f.read_text()); d = doc.get("data", doc)
        name = d.get("name")
        if not name: continue
        cur = ro.setdefault(name, {"active": True, "lane": "regular", "week": {}, "days_off": []})
        for k in FIELDS:
            if k in d and d[k] is not None and cur.get(k) != d[k]:
                cur[k] = d[k]; changed.append(f"{name}: {k}")
    p.write_text(json.dumps(rules, indent=2) + "\n")
    print("synced roster:", ", ".join(changed) if changed else "no changes")


if __name__ == "__main__":
    main(sys.argv[1])
