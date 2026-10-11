"""Backtest: should a rep's last 30/45/90 days of results bump his odds on top of the model? Usage: python tests/backtest_recent_form.py <job export csv>
Result Oct 11 2026: every version predicted worse than the model alone (log loss 0.575 -> 0.576 to 0.583). Hot streaks cool off on average. Not used
automatically; a manager boost for hot reps is a separate, tracked decision."""
import sys, numpy as np, pandas as pd
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
import engine as E
from sklearn.metrics import log_loss, roc_auc_score
df = E.load(sys.argv[1]); t = E.tuned(); today = pd.Timestamp('2026-10-11')
first = (today - pd.offsets.MonthBegin(1)).normalize() - pd.DateOffset(months=6)
cfgs = [(w, k) for w in (30, 45, 90) for k in (10, 20, 40)]
rows = {c: [] for c in cfgs}; base = []
for M in pd.date_range(first, periods=6, freq='MS'):
    end = M + pd.offsets.MonthEnd(0)
    if end > today - pd.Timedelta(days=14): break
    Stt, x = E.training(df, M - pd.Timedelta(days=1)); mc, ms = E.fit_both(x, M, t)
    Sn, xn = E.training(df, end); te = xn[(xn.date >= M) & (xn.date <= end)]
    p = mc.predict(te); base.append(pd.DataFrame({'p': p, 'y': te.y_close.values, 'rep': te.rep.values}))
    tr = x[x.ok_close] if 'ok_close' in x else x
    ptr = mc.predict(tr)
    for (w, k) in cfgs:
        rec = (tr.date >= M - pd.Timedelta(days=w)).values
        g = pd.DataFrame({'rep': tr.rep.values[rec], 'y': tr.y_close.values[rec], 'p': ptr[rec]}).groupby('rep').agg(sy=('y', 'sum'), sp=('p', 'sum'), n=('y', 'size'))
        adj = ((g.sy - g.sp) / (g.n + k)).to_dict()
        q = np.clip(p + np.array([adj.get(r, 0) for r in te.rep.values]), .01, .95)
        rows[(w, k)].append(pd.DataFrame({'p': q, 'y': te.y_close.values, 'rep': te.rep.values}))
b = pd.concat(base); print('base', round(log_loss(b.y, b.p), 4), round(roc_auc_score(b.y, b.p), 3))
for c, v in rows.items():
    d = pd.concat(v); print(c, round(log_loss(d.y, d.p), 4), round(roc_auc_score(d.y, d.p), 3))
