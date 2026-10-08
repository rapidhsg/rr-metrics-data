"""Safety check that runs whenever the rules change.

Fails (red X in Actions, plus an email) if:
  - settings.json is broken, or the calculation code errors, or
  - a name in settings.json does not exist anywhere in the AccuLynx data (almost always a typo,
    which would otherwise silently match nothing and quietly change the numbers).
Usage: python scripts/check_rules.py path/to/job_export_raw_latest.csv
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "rules"))
import rr_metrics as rr  # noqa: E402  (also proves settings.json is valid)

df = rr.load(sys.argv[1])
S = rr.S
problems = []


def must_exist(values, column, label):
    present = set(df[column].dropna().astype(str))
    for v in values:
        if v not in present:
            problems.append(f'{label}: "{v}" is not in the AccuLynx "{column}" column (typo?)')


must_exist(rr.SALES_TEAM, "Primary Salesperson", "sales_team")
for key, values in S["dead_reasons"].items():
    if not key.startswith("_"):
        must_exist(values, "Dead Lead Reason", f"dead_reasons.{key}")
for key in ["contacts_leads_appointments_exclude", "close_rate_exclude"]:
    must_exist(S["work_types"][key], "Work Type", f"work_types.{key}")
must_exist([S["work_types"]["upgrade"]], "Work Type", "work_types.upgrade")
must_exist(S["job_categories"]["close_rate_exclude"], "Job Category", "job_categories.close_rate_exclude")
for key, values in S["flags"].items():
    if isinstance(values, list):
        must_exist(values, "Dead Lead Reason", f"flags.{key}")

# Run the math end to end so a code error shows up here, not in someone's chat.
end = df["Lead Milestone Date"].max()
start, end = rr.rolling(end, 90)
m = rr.metrics(df, start, end)
rr.flags(df, start, end)
print(f"Rolling 90 ending {end.date()}: {m}")

# Job Expenses report, if present next to the job export.
exp_path = Path(sys.argv[1]).with_name("job_expenses_latest.csv")
if exp_path.exists():
    ex = rr.load_expenses(exp_path)
    jc = rr.job_costs(ex, df, start, end)
    print(rr.cost_summary(jc)[["Jobs", "Job Value", "GP %", "Material %", "Labor %"]].to_string())
    rr.expense_flags(ex, df, start, end)
    unknown = sorted(set(ex["Job Number"]) - set(df["Job Number"].dropna()))
    if unknown:
        problems.append(f"{len(unknown)} jobs in the expenses report are missing from the job export, e.g. {unknown[:3]}")

if problems:
    print("\nPROBLEMS FOUND:\n" + "\n".join(problems))
    sys.exit(1)
print("\nRules check passed.")
