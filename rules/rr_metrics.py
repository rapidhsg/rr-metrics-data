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
    res = {}
    for k, v in out.items():
        t = df.loc[v, cols].copy()
        t.loc[t["Primary Salesperson"].isin(HIDDEN), "Primary Salesperson"] = ""  # former reps never shown
        res[k] = t
    return res
