# Sales board engine learning log
Plain-English record of what the engine tested, learned and changed. Newest at the bottom.


## 2026-10-09 weekly self-test
- Tested on 641 sits (2026-04, 2026-05, 2026-06, 2026-07, 2026-08), training only on sits before each month.
- Close: top fifth predicted 46%, actually closed 47%. Bottom fifth predicted 18%, actually 19%. Ranking score (AUC) 0.635.
- Same-day close: top fifth predicted 26%, actually 27%. Bottom fifth 7%, actually 5%. AUC 0.708.
- Settings: old sits fade by half every 9999 days, shrinkage strength 0.1. CHANGED this week because it predicted better.
- Same-day sale worth $6,470 vs $5,531 for a later sale, so same-day close counts 0.17x on top of close.
- Own predictions vs results: {'n': 0, 'note': 'not enough finished sits yet to judge'}.
