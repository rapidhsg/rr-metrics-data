"""What actually happened, appointment by appointment, so the engine can learn from it.
For every past appointment the engine planned, one row in memory/outcomes.csv:
  - recommended: the rep the engine picked (last plan before the appointment day) and its predicted close
  - board: the rep on the sales board after manager moves and day-off changes (memory/board_moves.csv)
  - actual: the rep who ran it in AccuLynx, the engine's predicted close for that rep
  - result: sat (estimate given), sold, sold the same day; updated every run as late sales come in
  - followed: did the actual rep match the engine? did he match the board?
Run after each engine run. Usage: python outcomes.py <job export csv> [today]
Also: python outcomes.py --save-board <folder of cards/*.json exported from the board> [today]
      copies the board's manager moves into memory/board_moves.csv (one snapshot per day)."""
import json, sys
from datetime import datetime
from pathlib import Path
import pandas as pd
import engine as E

MEM = E.MEM


def save_board(folder, today):
    rows = []
    docs = [(f.stem, (lambda x: x.get("data", x))(json.loads(f.read_text()))) for f in sorted(Path(folder).glob("*.json"))]
    if not docs and (MEM / "board_moves.csv").exists():   # an empty export would wipe today's holds: keep the last snapshot instead
        print("board moves: no card docs exported, kept the last snapshot"); return
    has_rep = lambda d: "rep" in d and d.get("rep") != "__engine__"   # rep None = the manager pulled it to Needs a call
    real = lambda d: has_rep(d) and not d.get("pin")
    arranged = {(d.get("appt") or "")[:10] for _, d in docs if real(d)}   # days the manager actually moved a card on
    for guid, d in docs:
        held = has_rep(d) and (real(d) or (d.get("appt") or "")[:10] in arranged)   # a hold only counts on a day he arranged
        rows.append(dict(snap_date=today, guid=guid, board_rep=(d["rep"] or "") if held else "",
                         moved=held, held_only=bool(d.get("pin")), set_in_acculynx=bool(d.get("set")), moved_at=d.get("at") or ""))
    p = MEM / "board_moves.csv"; new = pd.DataFrame(rows, columns=["snap_date", "guid", "board_rep", "moved", "held_only", "set_in_acculynx", "moved_at"])
    if p.exists():
        old = pd.read_csv(p, dtype=str); new = pd.concat([old[old.snap_date != today], new.astype(str)])
    new.to_csv(p, index=False)
    print(f"board moves saved: {int(sum(r['moved'] for r in rows))} moved cards, {len(rows)} cards with board changes")


def main(path, today):
    today = pd.Timestamp(today).normalize()
    plans = pd.read_csv(MEM / "plans.csv", dtype=str)
    preds = pd.read_csv(MEM / "predictions.csv", dtype=str)
    plans["appt_day"] = plans.appt.str[:10]
    plans = plans[(plans.run_date <= plans.appt_day) & (plans.appt_day < today.strftime("%Y-%m-%d"))]
    if plans.empty: print("no finished planned appointments yet"); return
    # the engine's pick before the day started (on the day itself, started appointments are locked to their AccuLynx rep);
    # same-day bookings only have the day-of plan
    before = plans[plans.run_date < plans.appt_day]
    sameday = plans[~plans.guid.isin(before.guid)]
    last = pd.concat([before.sort_values("run_date").groupby("guid").last().reset_index(),
                      sameday.sort_values("run_date").groupby("guid").first().reset_index()], ignore_index=True)
    preds = preds[preds.run_date <= preds.appt_date].sort_values("run_date").groupby(["guid", "rep"]).last().reset_index()
    pc = preds.set_index(["guid", "rep"])["close"].astype(float).to_dict()
    lead_base = preds.assign(c=preds.close.astype(float)).groupby("guid").c.mean().to_dict()   # how good the lead was, any rep
    bm = MEM / "board_moves.csv"
    board = {}
    if bm.exists():
        b = pd.read_csv(bm, dtype=str).fillna("")
        for g, grp in b.sort_values("snap_date").groupby("guid"):
            r = grp.iloc[-1]; board[g] = r.board_rep if r.moved == "True" else None
    df = E.load(path).set_index("guid")
    out = []
    for r in last.itertuples():
        if r.guid not in df.index: continue
        j = df.loc[r.guid]; j = j.iloc[0] if isinstance(j, pd.DataFrame) else j
        actual = j["Primary Salesperson"] if isinstance(j["Primary Salesperson"], str) else ""
        rec = r.rep if isinstance(r.rep, str) else ""
        brd = board.get(r.guid) or rec
        ap, ia = j["Approved Milestone Date"], j["Initial Appointment Date"]
        sat = bool(j["Primary Estimate Total"] > 0)
        sold = bool(pd.notna(ap)); same = bool(sold and (ap.normalize() - ia.normalize()).days <= 0)
        out.append(dict(appt=r.appt, guid=r.guid, plan_run=r.run_date, arm=getattr(r, "arm", "champion") if isinstance(getattr(r, "arm", None), str) else "champion",
                        lead_base=round(lead_base.get(r.guid, float("nan")), 4),
                        recommended=rec, rec_close=pc.get((r.guid, rec), ""), board=brd, board_close=pc.get((r.guid, brd), ""),
                        actual=actual, actual_close=pc.get((r.guid, actual), ""),
                        followed_engine=actual == rec, followed_board=actual == brd, manager_moved=brd != rec,
                        sat=sat, sold=sold, sold_same_day=same, status=j["Current Milestone"], checked=today.strftime("%Y-%m-%d")))
    o = pd.DataFrame(out).sort_values("appt")
    o.to_csv(MEM / "outcomes.csv", index=False)
    s = o[o.sat]
    def rate(x): return f"{x.sold.mean():.0%} ({int(x.sold.sum())} of {len(x)})" if len(x) else "none yet"
    print(f"outcomes: {len(o)} finished planned appointments, {len(s)} sat")
    print(f"  ran by the engine's pick: {rate(s[s.followed_engine])} | ran by someone else: {rate(s[~s.followed_engine])}")
    print(f"  manager moved on the board: {rate(s[s.manager_moved])}")


def accuracy(path, today):
    """For every finished day: what the board predicted (last run before that day) vs what happened.
    Sales are counted by appointment day (the same cohort the prediction was for), and keep updating as late deals sign."""
    today = pd.Timestamp(today).normalize(); fp = MEM / "forecasts.csv"
    if not fp.exists(): print("no forecasts logged yet"); return
    f = pd.read_csv(fp, dtype={"run_date": str, "appt_day": str})
    f = f[(f.run_date < f.appt_day) & (f.appt_day < today.strftime("%Y-%m-%d"))]
    if f.empty: print("accuracy: no finished forecast days yet"); return
    f = f.sort_values("run_date").groupby("appt_day").last().reset_index()
    df = E.load(path); ia = df["Initial Appointment Date"].dt.normalize()
    m = E.rr.masks(df, today - pd.Timedelta(days=400), today)
    rows = []
    for r in f.itertuples():
        d = pd.Timestamp(r.appt_day); on = ia == d
        sits = m["close_sits_company"] & on; sold = sits & df["Approved Milestone Date"].notna()
        same = sold & (df["Approved Milestone Date"].dt.normalize() == d)
        appts = on & df["Prospect Milestone Date"].notna() & ~df._cb
        rows.append(dict(appt_day=r.appt_day, predicted_on=r.run_date, booked_then=int(r.booked), still_to_book_pred=r.still_to_book,
                         appts_actual=int(appts.sum()), sits_actual=int(sits.sum()),
                         exp_sales=r.exp_sales, sold_actual=int(sold.sum()), exp_sales_usd=r.exp_sales_usd, sold_usd_actual=round(float(df.loc[sold, "Contract Amount"].sum())),
                         exp_same_day=r.exp_same_day, same_day_actual=int(same.sum()), checked=today.strftime("%Y-%m-%d")))
    a = pd.DataFrame(rows); a.to_csv(MEM / "accuracy_daily.csv", index=False)
    print(f"accuracy: {len(a)} finished days. Predicted {a.exp_sales.sum():.1f} sales, actual {a.sold_actual.sum()} so far; "
          f"predicted ${a.exp_sales_usd.sum():,.0f}, actual ${a.sold_usd_actual.sum():,.0f}; bookings forecast {a.booked_then.sum() + a.still_to_book_pred.fillna(0).sum():.0f}, actual {a.appts_actual.sum()}")


if __name__ == "__main__":
    if sys.argv[1] == "--save-board":
        save_board(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else datetime.now().strftime("%Y-%m-%d"))
    else:
        t = sys.argv[2] if len(sys.argv) > 2 else datetime.now()
        main(sys.argv[1], t); accuracy(sys.argv[1], t)
