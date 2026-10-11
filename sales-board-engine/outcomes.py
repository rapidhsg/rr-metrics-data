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
    for f in sorted(Path(folder).glob("*.json")):
        doc = json.loads(f.read_text()); d = doc.get("data", doc)
        rows.append(dict(snap_date=today, guid=f.stem, board_rep="" if d.get("rep") in (None, "__engine__") else d["rep"],
                         moved=d.get("rep") not in (None, "__engine__"), set_in_acculynx=bool(d.get("set")), moved_at=d.get("at") or ""))
    p = MEM / "board_moves.csv"; new = pd.DataFrame(rows, columns=["snap_date", "guid", "board_rep", "moved", "set_in_acculynx", "moved_at"])
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
    last = plans.sort_values("run_date").groupby("guid").last().reset_index()        # the plan as of the appointment day
    preds = preds[preds.run_date <= preds.appt_date].sort_values("run_date").groupby(["guid", "rep"]).last().reset_index()
    pc = preds.set_index(["guid", "rep"])["close"].astype(float).to_dict()
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
        out.append(dict(appt=r.appt, guid=r.guid, plan_run=r.run_date,
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


if __name__ == "__main__":
    if sys.argv[1] == "--save-board":
        save_board(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else datetime.now().strftime("%Y-%m-%d"))
    else:
        main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else datetime.now())
