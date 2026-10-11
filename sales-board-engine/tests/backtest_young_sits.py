"""Backtest: does learning from sits younger than the 14-day wait help? Trains on each of the last 6 months using only what was known then,
scores against final outcomes. Usage: python tests/backtest_young_sits.py <job export csv>
Result Oct 11 2026: new reps log loss 0.4917 -> 0.4862 (better), all sits 0.5738 -> 0.5756 (about the same). Kept on."""
import sys, numpy as np, pandas as pd
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
import engine as E
from sklearn.metrics import log_loss, roc_auc_score
df = E.load(sys.argv[1]); t = E.tuned(); today = pd.Timestamp('2026-10-11')
_, xall = E.training(df, today)          # outcomes as known now
first = (today - pd.offsets.MonthBegin(1)).normalize() - pd.DateOffset(months=6)
res = {False: [], True: []}
for M in pd.date_range(first, periods=6, freq='MS'):
    end = M + pd.offsets.MonthEnd(0)
    if end > today - pd.Timedelta(days=21): break
    _, x = E.training(df, M - pd.Timedelta(days=1))
    te = xall[(xall.date >= M) & (xall.date <= end)]
    newr = te.rep_n.lt(25).values
    for young in (False, True):
        E.CFG["use_young_sits"] = young
        mc, ms = E.fit_both(x, M, t); p = mc.predict(te)
        res[young].append(pd.DataFrame({'p': p, 'y': te.y_close.values, 'new': newr}))
for k, v in res.items():
    d = pd.concat(v); n = d[d.new]
    print('young' if k else 'base ', 'all', round(log_loss(d.y, d.p), 4), round(roc_auc_score(d.y, d.p), 3), 'pred', round(d.p.mean(), 3), 'act', round(d.y.mean(), 3),
          '| new reps n', len(n), 'loss', round(log_loss(n.y, n.p), 4) if len(n) else '-', 'pred', round(n.p.mean(), 3) if len(n) else '-', 'act', round(n.y.mean(), 3) if len(n) else '-')
