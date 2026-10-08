"""Rapid Roofing metrics. Reproduces the certified AccuLynx reports exactly.

All lists (roster, dead reasons, work types...) come from settings.json next to this file.
Usage:
    import sys; sys.path.insert(0, "rr-metrics-data/rules")
    import rr_metrics as rr
    df = rr.load("rr-data/data/job_export_raw_latest.csv")
    rr.metrics(df, "2026-07-01", "2026-09-30")
"""
import json
from pathlib import Path

import pandas as pd

S = json.loads((Path(__file__).parent / "settings.json").read_text())
SALES_TEAM = [k for k in S["sales_team"] if not k.startswith("_")]
HIDDEN = set(S["hidden_former_reps"]["names"])
DR, WT, MS = S["dead_reasons"], S["work_types"], S["milestones"]
UPG = WT["upgrade"]


def load(path):
    df = pd.read_csv(path, low_memory=False)
    for c in [c for c in df.columns if c.endswith("Date") and "Days" not in c]:
        df[c] = pd.to_datetime(df[c].astype(str).str.split(" ").str[0], format="%m/%d/%y", errors="coerce")
    df["_dead"] = df["Dead Lead Reason"].fillna("")  # exact-name matching only
    df["_wt"] = df["Work Type"].fillna("")
    df["_cb"] = df["Job Trade Type"].fillna("").str.contains(S["call_back_text"])
    return df


def window(df, col, start, end):
    return (df[col] >= pd.Timestamp(start)) & (df[col] <= pd.Timestamp(end))


def rolling(today, days):
    t = pd.Timestamp(today).normalize()
    return t - pd.Timedelta(days=days), t  # both days included (rolling 90 on Oct 7 = Jul 9 to Oct 7)


def last_week(today):
    t = pd.Timestamp(today).normalize()
    monday = t - pd.Timedelta(days=t.weekday())
    return monday - pd.Timedelta(days=7), monday - pd.Timedelta(days=1)  # previous Monday to Sunday


def masks(df, start, end, reps=None):
    """Boolean masks for every metric. Group any of them by rep or source for breakdowns."""
    d, wt, cb = df["_dead"], df["_wt"], df["_cb"]
    m = {}
    m["contacts"] = window(df, "Lead Milestone Date", start, end) & ~cb & ~wt.isin(WT["contacts_leads_appointments_exclude"]) & ~d.isin(DR["contacts_exclude"])
    m["leads"] = window(df, "Lead Milestone Date", start, end) & ~cb & ~wt.isin(WT["contacts_leads_appointments_exclude"]) & ~d.isin(DR["leads_and_appointments_exclude"])
    m["appointments"] = window(df, "Prospect Milestone Date", start, end) & ~cb & ~wt.isin(WT["contacts_leads_appointments_exclude"]) & ~d.isin(DR["leads_and_appointments_exclude"])
    m["sits"] = window(df, "Initial Appointment Date", start, end) & (df["Primary Estimate Total"] > 0) & ~d.isin(DR["sits_exclude"])
    m["sales"] = window(df, "Approved Milestone Date", start, end) & df["Current Milestone"].isin(MS["sales_count_if_currently"]) & ~cb
    m["jobs_sold"] = m["sales"] & (wt != UPG)
    m["revenue"] = window(df, "Completed Milestone Date", start, end) & df["Current Milestone"].isin(MS["revenue_count_if_currently"]) & ~cb
    m["jobs_installed"] = m["revenue"] & (wt != UPG)
    m["upgrades"] = m["revenue"] & (wt == UPG)
    m["close_sits_company"] = (window(df, "Initial Appointment Date", start, end) & (df["Primary Estimate Total"] > 0)
                               & ~d.isin(DR["close_rate_exclude"]) & ~cb
                               & ~df["Job Category"].isin(S["job_categories"]["close_rate_exclude"])
                               & ~wt.isin(WT["close_rate_exclude"]))
    m["close_sits_team"] = m["close_sits_company"] & df["Primary Salesperson"].isin(reps if reps is not None else SALES_TEAM)
    sold = df["Approved Milestone Date"].notna()
    m["close_sold_company"] = m["close_sits_company"] & sold
    m["close_sold_team"] = m["close_sits_team"] & sold
    closed = m["revenue"] & (df["Current Milestone"] == "Closed") & (wt != UPG)
    m["gp_jobs"] = closed & (df["Profit"] != 0) & (df["Profit %"] != 1)
    return m


def metrics(df, start, end, reps=None):
    m = masks(df, start, end, reps)
    ca = df["Contract Amount"]
    o = {k: int(m[k].sum()) for k in ["contacts", "leads", "appointments", "sits", "jobs_sold", "jobs_installed",
                                      "close_sold_team", "close_sits_team", "close_sold_company", "close_sits_company"]}
    o["sales"] = round(ca[m["sales"]].sum(), 2)
    o["revenue"] = round(ca[m["revenue"]].sum(), 2)
    o["upgrades"] = round(ca[m["upgrades"]].sum(), 2)
    o["gp_profit_closed"] = round(df.loc[m["gp_jobs"], "Profit"].sum(), 2)
    o["gp_contract_closed"] = round(ca[m["gp_jobs"]].sum(), 2)
    return o  # rates are always total / total from these counts


def by_rep(df, mask, value=None):
    """Count (or sum a column) per rep, with former reps removed."""
    s = df[mask & ~df["Primary Salesperson"].isin(HIDDEN)]
    g = s.groupby("Primary Salesperson")
    return (g[value].sum() if value else g.size()).sort_values(ascending=False)


def revenue_in_progress(rip_path, start=None, end=None):
    r = pd.read_csv(rip_path)
    r["RR"] = r["Job Number"] if "Job Number" in r else r["Job Name"].str.extract(r"(RR-\d+)")[0]
    r["Crew End Date"] = pd.to_datetime(r["Crew End Date"].str.split(" ").str[0], format="%m/%d/%y")
    if start is not None:
        r = r[(r["Crew End Date"] >= pd.Timestamp(start)) & (r["Crew End Date"] <= pd.Timestamp(end))]
    jobs = r.drop_duplicates("RR")  # Job Value repeats on every trade row
    return round(jobs["Job Value"].sum(), 2), len(jobs)


def discounts(df, start, end):
    """Sold jobs in the window (Approved date) with their discount %. Discount % = discount / price before discount.
    Over the max (20%, all three discounts stacked), the rep owes 50% of the overage."""
    D = S["discounts"]
    m = (window(df, "Approved Milestone Date", start, end) & (df["Contract Amount"] > 0)
         & (df["_wt"] != UPG) & ~df["_cb"])
    t = df.loc[m, ["Job Number", "Primary Salesperson", "Approved Milestone Date", "Contract Amount", "Discount Amount", "Job Number Url"]].copy()
    disc = -t["Discount Amount"].fillna(0)
    t["Price Before Discount"] = t["Contract Amount"] + disc
    t["Discount %"] = (disc / t["Price Before Discount"] * 100).round(2)
    over = (disc - t["Price Before Discount"] * D["max_total_pct"] / 100).clip(lower=0).round(2)
    t["Over Max $"] = over
    t["Rep Owes $"] = (over * D["rep_pays_share_of_overage"]).round(2)
    t.loc[t["Primary Salesperson"].isin(HIDDEN), "Primary Salesperson"] = ""
    return t


def flags(df, start, end):
    F = S["flags"]
    d = df["_dead"]
    # No customer names: flags show the RR number (if any) and the AccuLynx link.
    want = ["Job Number", "Dead Lead Reason", "Primary Salesperson", "Appointment Set By", "Job Number Url", "Job Name Url"]
    cols = [c for c in want if c in df.columns]
    if "Job Number Url" in cols and "Job Name Url" in cols:
        cols.remove("Job Name Url")
    out = {
        "quoted_but_marked_not_serviced": window(df, "Initial Appointment Date", start, end) & (df["Primary Estimate Total"] > 0) & d.isin(F["quoted_but_marked_not_serviced"]),
        "booked_but_should_not_be": window(df, "Prospect Milestone Date", start, end) & d.isin(F["booked_but_should_not_be"]),
        "trade_not_serviced_on_main_trade": window(df, "Lead Milestone Date", start, end) & d.str.startswith("Trade Not Serviced") & df["Job Trade Type"].fillna("").str.contains(F["main_trade"]),
        "appointment_with_no_setter": window(df, "Prospect Milestone Date", start, end) & df["Appointment Set By"].isna() & ~df["_cb"] & ~df["_wt"].isin(WT["contacts_leads_appointments_exclude"]),
        "closed_with_bad_profit": window(df, "Closed Milestone Date", start, end) & (df["Current Milestone"] == "Closed") & ~df["_cb"] & ((df["Profit"] <= 0) | (df["Profit %"] == 1)),
    }
    res = {"discount_over_max": discounts(df, start, end).query("`Over Max $` > 0.5")}
    for k, v in out.items():
        t = df.loc[v, cols].copy()
        t.loc[t["Primary Salesperson"].isin(HIDDEN), "Primary Salesperson"] = ""  # former reps never shown
        res[k] = t
    return res


# ---------------------------------------------------------------------------
# Job Expenses report (data/job_expenses_latest.csv): every cost line on Closed jobs.
# ---------------------------------------------------------------------------
EX = S["expenses"]


def load_expenses(path):
    """One row per cost line, with a Bucket (Material, Labor, Dump, Commission...) and a Crew for labor/dump lines."""
    e = pd.read_csv(path, low_memory=False)
    for c in ["Payment Amount", "Job Value", "Additional Expenses", "Total Expenses", "Balance Due"]:
        e[c] = pd.to_numeric(e[c], errors="coerce")
    e = e[e["Total Expenses"].notna() & e["Job Number"].astype(str).str.startswith("RR-")].copy()  # drops the odd broken row
    t = e["To/Method"].fillna("").str.strip()
    e["Bucket"] = "Other"
    done = pd.Series(False, index=e.index)
    for bucket, pattern in EX["buckets"]:
        hit = ~done & t.str.contains(pattern, case=False, regex=True)
        e.loc[hit, "Bucket"] = bucket
        done |= hit
    e.loc[e["Payment Type"].eq("Additional"), "Bucket"] = "Commission"
    crew = (t.str.replace(r"(?i)^(labor|other job expenses)\s+", "", regex=True)
             .str.replace(r"(?i)\bcash\b\s*", "", regex=True)
             .str.replace(r"(?i)\s+(pay adj|pay|dump)$", "", regex=True)
             .str.replace(r"(?i),?\s+(inc|llc|corp)\.?$", "", regex=True)
             .str.replace(r"(?i)^ian\s+", "", regex=True).str.strip())
    crew = crew.where(~crew.str.lower().eq("renewusa solar"), "RenewUSA Solar")
    odd = t.str.lower().str.contains("|".join(EX["odd_line_words"]))
    e["Crew"] = crew.where(e["Bucket"].isin(["Labor", "Dump"]) & ~odd)  # food and test lines are not a crew
    return e


def job_costs(exp, df, start=None, end=None):
    """One row per Closed job: cost by bucket, Profit and GP % (from the job export), rep, crews.
    Window = Completed (install) date, same as Revenue and GP %. "In GP" marks the jobs the GP % rule counts."""
    piv = exp.pivot_table(index="Job Number", columns="Bucket", values="Payment Amount", aggfunc="sum", fill_value=0)
    first = exp.groupby("Job Number").agg(**{"Job Value": ("Job Value", "first"), "Total Expenses": ("Total Expenses", "first"),
                                            "Balance Due": ("Balance Due", "first"), "Job Number Url": ("Job Number Url", "first")})
    crews = exp.dropna(subset=["Crew"]).groupby("Job Number")["Crew"].agg(lambda s: ", ".join(dict.fromkeys(s)))
    j = df.set_index("Job Number")[["Primary Salesperson", "Work Type", "Job Trade Type", "Job Category", "Completed Milestone Date", "Closed Milestone Date", "Profit", "Profit %"]]
    out = first.join(piv).join(crews.rename("Crews")).join(j, how="left")
    out["GP %"] = (out["Profit"] / out["Job Value"] * 100).round(2)
    cb = out["Job Trade Type"].fillna("").str.contains(S["call_back_text"])
    out["In GP"] = (out["Work Type"] != UPG) & ~cb & (out["Profit"] != 0) & (out["Profit %"] != 1)
    if start is not None:
        out = out[window(out, "Completed Milestone Date", start, end)]
    out.loc[out["Primary Salesperson"].isin(HIDDEN), "Primary Salesperson"] = ""
    return out


def cost_summary(jc, by=None):
    """Totals and % of job value per bucket, plus GP % vs the goal. Uses only the jobs the GP % rule counts
    (no upgrades, no Call Backs, no $0 or 100% profit), so GP % here always equals the GP % metric. Optional group by a column."""
    jc = jc[jc["In GP"]]
    buckets = [b for b, _ in EX["buckets"]] + ["Other"]
    cols = [b for b in buckets if b in jc.columns]

    def one(g):
        v = g["Job Value"].sum()
        row = {"Jobs": len(g), "Job Value": round(v, 2), "Profit": round(g["Profit"].sum(), 2),
               "GP %": round(g["Profit"].sum() / v * 100, 2) if v else None}
        for b in cols:
            row[b] = round(g[b].sum(), 2)
            row[b + " %"] = round(g[b].sum() / v * 100, 2) if v else None
        return pd.Series(row)

    res = jc.groupby(by).apply(one) if by else one(jc).to_frame("All").T
    res["GP goal %"] = EX["gp_goal_pct"]
    return res


def expense_flags(exp, df, start, end):
    """Cost data that looks wrong on Closed jobs in the window."""
    jc = job_costs(exp, df, start, end)
    wt_ok = jc["Work Type"].isin(EX["flag_no_material_or_labor_work_types"]) & (jc["Job Value"] > 0)
    get = lambda b: jc[b] if b in jc.columns else 0
    odd = exp[exp["To/Method"].fillna("").str.lower().str.contains("|".join(EX["odd_line_words"]))
              & exp["Job Number"].isin(jc.index)]
    cols = ["Primary Salesperson", "Work Type", "Job Value", "Completed Milestone Date", "Job Number Url"]
    return {
        "closed_with_no_material": jc.loc[wt_ok & (get("Material") <= 0), cols],
        "closed_with_no_labor": jc.loc[wt_ok & (get("Labor") <= 0), cols],
        "sales_rep_job_with_no_commission": jc.loc[jc["Primary Salesperson"].isin(SALES_TEAM) & (jc["Work Type"] != UPG)
                                                   & (jc["Job Value"] > 0) & (get("Commission") <= 0), cols],
        "returns_bigger_than_material": jc.loc[(get("Material") < 0), cols],
        "commission_paid_on_low_gp": jc.loc[jc["In GP"] & (get("Commission") > 0)
                                            & (jc["GP %"] < EX["flag_commission_when_gp_below_pct"]), cols + ["GP %"]],
        "odd_expense_lines": odd[["Job Number", "To/Method", "Payment Amount", "Memo/Notes", "Job Number Url"]],
    }
