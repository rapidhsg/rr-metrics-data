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

## 2026-10-11 rules rebuilt around money, hot reps and real schedules
- Money first: every appointment goes to the best close chance inside hours, limits and caps. Weekly minimums cut to a small tiebreaker.
- Hot hand: Beast-level close (35%+ rolling 30, 15+ sits) earns Beast whatever the start date; off below 30%. Franco is hot (52% on 21 sits).
- Promise: 7 a week on a rolling quarter, scaled to the schedule a rep makes available (full = 11 of 14 days, usual hours). Francesco 5.1 (Mon to Fri, home by 4:30), Joe 5.6.
- Days off from the board now reach the engine (sync_roster.py). Francesco off Mon 10/12 and Wed 10/14; Franco picks up 5 of those appointments.

## 2026-10-11 engine learns from young sits
- Found: sits newer than the 14-day close wait were ignored, so a new rep's first two weeks were invisible (Franco: 0 of 21 sits used, scored like an average new rep at about 24%).
- Change: young sold sits count as sales; young unsold sits count as a partial sale (share of older sits still unsold at that age that sold later). Labels only use approvals known on the training date.
- Backtest vs final outcomes, last 6 months: new reps log loss 0.4917 -> 0.4862 (better), all sits 0.5738 -> 0.5756 (about the same). Franco now about 34% on upcoming leads, Steve about 23%.
- Also tested: bumping odds by a rep's last 30/45/90 days of results. Every version predicted worse (hot streaks cool off on average), so it is not automatic.
- New regression test tests/test_rules.py checks hours, days off, lanes, daily limits, the 2-hour gap, no 5th sit, hot ratings and promises on every plan.

## 2026-10-11 rules made evergreen
- No rule or piece of code names a person anymore. Lanes, ratings, hot status, promises, hours and days off come from each rep's data and Reps tab settings. Display names come from "Show as" on the Reps tab. Plan unchanged (9.6 expected sales); rules test passes.

## 2026-10-11 routes count
- Driving now counts a little in the plan: 0.5 points of close chance per 10 miles between back-to-back appointments (half for the drive from home or the office).
- On the next two weeks: driving 715 -> 580 miles (19% less) for 0.02 fewer expected sales (about $350) and 0.09 fewer same-day signs. Doubling the weight saved only 16 more miles, so 0.5 stays.

## 2026-10-11 note signal fix
- "No leak" notes were also being counted as "leak" (259 of 274). The leak signal now skips "no leak", "not leaking" and "isn't leaking". Backtest, last 6 months: log loss 0.5756 -> 0.5745, ranking 0.634 -> 0.636 (better).

## 2026-10-11 tracking predictions over time
- Every run now logs what the board predicts for each upcoming day (memory/forecasts.csv): appointments booked, expected sales and $, same-day signs and $, bookings still to come, full-team value.
- After each day finishes, outcomes.py scores it (memory/accuracy_daily.csv): predicted vs actual appointments, sales, $ and same-day signs, updated as late deals sign. The weekly self-test reports it and the Results tab shows it.

## 2026-10-11 assignment logic improves itself
- New weekly step learn.py tests the assignment dials live on alternating days and keeps a new value only when it closes clearly more (60+ sits per side, 2+ points better after adjusting for lead quality, z 1.64). Hard rules never change.
- First test from 2026-10-12: hot streak boost 0 (today) vs 0.5 (hot reps get half their edge over their usual odds as extra weight). Next up: driving weight, then same-day weight.
