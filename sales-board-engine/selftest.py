"""Weekly self-test and retune.
1. Walk-forward test: for each of the last 6 full months, train only on sits before that month, predict that month, compare to what happened.
2. Try each tuning setting in settings.json tuning_grid; keep the current one unless another beats it by retune_min_gain.
3. Work out the same-day weight from data.
4. Check the engine's own logged predictions against results (self-correction factor).
Writes memory/tuned.json and adds an entry to memory/learning_log.md.
Usage: python selftest.py <path to job_export_raw_latest.csv> [today]"""
import json, sys
from datetime import datetime
import numpy as np, pandas as pd
from sklearn.metrics import log_loss, roc_auc_score
import engine as E

def walk_forward(df, today, t, months=6):
    today = pd.Timestamp(today).normalize()
    first = (today - pd.offsets.MonthBegin(1)).normalize() - pd.DateOffset(months=months)
    res = {"close": [], "same": []}
    for M in pd.date_range(first, periods=months, freq="MS"):
        end = M + pd.offsets.MonthEnd(0)
        if end > today - pd.Timedelta(days=E.CFG["close_label_wait_days"]): break
        S, x = E.training(df, M - pd.Timedelta(days=1))
        mc, ms = E.fit_both(x, M, t)
        Sn, xn = E.training(df, end)
        te = xn[(xn.date >= M) & (xn.date <= end)]
        res["close"].append(pd.DataFrame({"p": mc.predict(te), "y": te.y_close.values, "rep": te.rep.values, "month": M.strftime("%Y-%m")}))
        res["same"].append(pd.DataFrame({"p": ms.predict(te), "y": te.y_same.values, "rep": te.rep.values, "month": M.strftime("%Y-%m")}))
    out = {}
    for k, v in res.items():
        d = pd.concat(v); q = pd.qcut(d.p.rank(method="first"), 5, labels=False)
        out[k] = dict(n=len(d), months=sorted(d.month.unique().tolist()), logloss=round(log_loss(d.y, d.p), 4), auc=round(roc_auc_score(d.y, d.p), 3),
                      top_fifth_pred=round(d.p[q == 4].mean(), 3), top_fifth_actual=round(d.y[q == 4].mean(), 3),
                      bottom_fifth_pred=round(d.p[q == 0].mean(), 3), bottom_fifth_actual=round(d.y[q == 0].mean(), 3),
                      avg_pred=round(d.p.mean(), 3), avg_actual=round(d.y.mean(), 3))
    return out

def own_predictions_check(df, today):
    """Compare the engine's logged predictions (for the rep who actually ran the sit) to what happened."""
    p = E.MEM / "predictions.csv"
    if not p.exists(): return None
    L = pd.read_csv(p, parse_dates=["run_date", "appt_date"])
    L = L.sort_values("run_date").groupby(["guid", "rep"]).last().reset_index()      # last prediction before the sit
    S, x = E.training(df, today)
    x = x[x.ok_close][["guid", "rep", "y_close", "y_same"]]
    j = L.merge(x, on=["guid", "rep"])
    if len(j) < 30: return dict(n=len(j), note="not enough finished sits yet to judge")
    return dict(n=len(j), pred_close=round(j.close.mean(), 3), actual_close=round(j.y_close.mean(), 3),
                pred_same=round(j.same_day.mean(), 3), actual_same=round(j.y_same.mean(), 3))

def main(path, today=None):
    today = pd.Timestamp(today or datetime.now()).normalize()
    df = E.load(path)
    t_now = E.tuned()
    grid = [dict(half_life_days=h, shrink_C=c) for h in E.CFG["tuning_grid"]["half_life_days"] for c in E.CFG["tuning_grid"]["shrink_C"]]
    scores = []
    for t in grid:
        r = walk_forward(df, today, t)
        scores.append((r["close"]["logloss"] + r["same"]["logloss"], t, r))
        print(t, r["close"]["auc"], r["same"]["auc"], flush=True)
    cur = next(s for s in scores if s[1] == {k: t_now[k] for k in ("half_life_days", "shrink_C")}) if any(s[1] == {k: t_now[k] for k in ("half_life_days", "shrink_C")} for s in scores) else min(scores, key=lambda s: s[0])
    best = min(scores, key=lambda s: s[0])
    changed = best[0] < cur[0] - E.CFG["retune_min_gain"]
    pick = best if changed else cur
    S, x = E.training(df, today)
    sdv = E.same_day_value(S)
    sdw = sdv["weight"] if E.CFG["same_day_weight"]["mode"] == "data" else float(E.CFG["same_day_weight"]["mode"])
    own = own_predictions_check(df, today)
    # self-correction: if logged predictions run high or low on 100+ finished sits, shift future predictions to match
    corr = {}
    if own and own.get("n", 0) >= 100:
        lg = lambda p: np.log(p / (1 - p))
        corr = dict(close=round(lg(own["actual_close"]) - lg(own["pred_close"]), 3), same_day=round(lg(own["actual_same"]) - lg(own["pred_same"]), 3))
    tj = dict(updated=today.strftime("%Y-%m-%d"), current=dict(pick[1], same_day_weight=sdw, correction=corr),
              test=pick[2], same_day_value=sdv, own_predictions=own,
              grid=[dict(s[1], score=round(s[0], 4), close_auc=s[2]["close"]["auc"], same_auc=s[2]["same"]["auc"]) for s in scores])
    (E.MEM / "tuned.json").write_text(json.dumps(tj, indent=1))
    c, s = pick[2]["close"], pick[2]["same"]
    lines = [f"\n## {today:%Y-%m-%d} weekly self-test",
             f"- Tested on {c['n']} sits ({', '.join(c['months'])}), training only on sits before each month.",
             f"- Close: top fifth predicted {c['top_fifth_pred']:.0%}, actually closed {c['top_fifth_actual']:.0%}. Bottom fifth predicted {c['bottom_fifth_pred']:.0%}, actually {c['bottom_fifth_actual']:.0%}. Ranking score (AUC) {c['auc']}.",
             f"- Same-day close: top fifth predicted {s['top_fifth_pred']:.0%}, actually {s['top_fifth_actual']:.0%}. Bottom fifth {s['bottom_fifth_pred']:.0%}, actually {s['bottom_fifth_actual']:.0%}. AUC {s['auc']}.",
             f"- Settings: old sits fade by half every {pick[1]['half_life_days']} days, shrinkage strength {pick[1]['shrink_C']}." + (" CHANGED this week because it predicted better." if changed else " No change."),
             f"- Same-day sale worth ${sdv['same_day_value']:,} vs ${sdv['later_value']:,} for a later sale, so same-day close counts {sdw:.2f}x on top of close.",
             f"- Own predictions vs results: {own if own else 'no logged predictions yet'}."]
    with open(E.MEM / "learning_log.md", "a") as f: f.write("\n".join(lines) + "\n")
    print("\n".join(lines))

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
