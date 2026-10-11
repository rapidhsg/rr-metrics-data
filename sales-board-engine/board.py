"""Build board.json for the dashboard from the engine's scores.json + plan.json and the job export.
One card per upcoming appointment: who the engine picked, every rep's odds, why, and what blocks each rep.
Customer name only. Phone numbers and emails are stripped from notes.
Usage: python board.py <out dir> <job export csv>   (reads <out>/scores.json and <out>/plan.json, writes <out>/board.json)"""
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


def main(out, path):
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
            lane=tag, booked_today=L.get("days_lead_to_appt") == 0, days_out=L.get("days_lead_to_appt"),
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
        disp, short = ro.get("display") or DISPLAY.get(name, (name, name.split()[0]))
        reps.append(dict(name=name, display=disp, short=short, rating=st["rating"], close=st["close"], sits=st["sits"], window=st["window"],
                         day=st["day"], limits={k: v for k, v in st["limits"].items() if not k.startswith("_")},
                         note=st.get("note"), this_week=st["this_week_so_far"], lane=ro.get("lane", "regular"),
                         week=ro.get("week", {})))
    full2short = {r["name"]: r["short"] for r in reps}
    for c in cards:
        if c["note"]:
            for full, sh in full2short.items(): c["note"] = c["note"].replace(full, sh)
    meta = dict(P["meta"]); meta.pop("solver", None)
    meta.update(data_as_of=S["meta"]["run"], sits_used=S["meta"]["sits_used"])
    json.dump(dict(meta=meta, reps=reps, cards=sorted(cards, key=lambda c: c["appt"])),
              open(out / "board.json", "w"), separators=(",", ":"), allow_nan=False)
    print(f"board.json: {len(cards)} cards, {len(reps)} reps")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
