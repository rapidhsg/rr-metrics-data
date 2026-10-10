# Sales board engine learning log
Plain-English record of what the engine tested, learned and changed. Newest at the bottom.


## 2026-10-09 weekly self-test
- Tested on 641 sits (2026-04, 2026-05, 2026-06, 2026-07, 2026-08), training only on sits before each month.
- Close: top fifth predicted 46%, actually closed 47%. Bottom fifth predicted 18%, actually 19%. Ranking score (AUC) 0.635.
- Same-day close: top fifth predicted 26%, actually 27%. Bottom fifth 7%, actually 5%. AUC 0.708.
- Settings: old sits fade by half every 9999 days, shrinkage strength 0.1. CHANGED this week because it predicted better.
- Same-day sale worth $6,470 vs $5,531 for a later sale, so same-day close counts 0.17x on top of close.
- Own predictions vs results: {'n': 0, 'note': 'not enough finished sits yet to judge'}.

## 2026-10-09 assignment added
- The engine now hands out appointments itself: the plan with the most expected closes that fits the rules (3 a day, 2 hours apart, hours and home-by times, lanes, weekly capacity). Rule bends only when an appointment would otherwise have nobody.
- Tested on 533 past sits (Apr to Aug), each month using only sits before it. With the reps who actually worked each day: predicted close rate 31.9% as assigned vs 33.5% with the engine's plan, same-day close 15.1% vs 16.9%. With every current rep available: 34.2% close and 18.6% same-day.

## 2026-10-10 assignment rules rebuilt
- All assignment rules moved into one file, assignment_rules.json: ratings (New, Coaching, Tenured, Beast, Lane) from the rolling 30 close rate, per-rating daily and weekly limits, Hero's Journey ramp for new reps, minimums first then feed the beasts, specialty not counted toward weekly numbers, commercial to Meinardus only, bends only to avoid nobody-free or keep a same-day appointment.
- Retested on 533 past sits (Apr to Aug), each month using only sits before it. Same reps who worked each day: predicted close 32.0% as assigned vs 33.5% with the plan, same-day close 15.1% vs 17.1%. Every current rep available: 34.3% close, 18.9% same-day.
- With the new weekly caps, 77 of those 533 past sits (14%) had nobody free within the rules on days only the reps who worked were available. Past volume ran above what the caps allow.
