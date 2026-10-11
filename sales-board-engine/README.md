# Sales board engine

Rates every upcoming appointment for every rep, so the sales board can recommend who should run each sit.
The goal is higher close rates and more same-day closes. The engine learns from results and corrects itself.

## Where the data comes from

Only the live AccuLynx job export on this repo's `data` branch (`data/job_export_raw_latest.csv`), loaded through the
certified rules code in `rules/rr_metrics.py`. Sits are counted with the certified close rate rules. Only the last
395 days are used (`data_window_days` in settings.json), because older data is not reliable.

## What it predicts

For every upcoming appointment and every rep on the board:

- **Close chance**: will this homeowner buy from this rep.
- **Same-day close chance**: will they sign at the first sit.
- **Pick score** = close chance + (same-day weight x same-day chance). The same-day weight is worked out from data every
  week: what a same-day sale is worth compared with a later sale (contract size x profit % x not cancelled).

Each rating comes with the top reasons pushing it up and down, in plain words, for the board's "Why this rep" section.

## How it decides

Two layers learned together from past sits:

1. **The lead**: lead source and sub source, area, time of day, weekday, days from lead to appointment, who set it,
   lead type (replacement or repair), roof age, note signals (leak, referral, price shopper, budget, first call,
   storm, urgency, insurance, both owners home, specialty, and more), and AI note tags.
2. **The rep**: how much better or worse each rep does than average, overall and on this kind of lead (type, area,
   source, time of day, and note signals).

Everything is pulled toward the team average until the data proves it. A rep with hundreds of sits stands on his own
record; a rep with 15 sits barely moves off average and moves more with every sit. Reps in their first 25 sits start
from what new reps have actually done, not from the team average.

## How it hands out appointments (`assign.py`)

All assignment rules live in ONE file: **`assignment_rules.json`**. Rep roster and hours, ratings, daily and weekly
limits, the Hero's Journey ramp, lanes, and when rules can bend. Nothing else in the repo repeats those numbers, so a
change there is the only change needed. The dashboard's Reps tab owns the roster; `sync_roster.py` copies it in before each run.

How it works, in words (rules as of Oct 11 2026). No rule names a person: who gets what comes only from each rep's data and settings, so anyone with the same numbers and settings is treated the same.

1. **Money first.** Every appointment goes to the rep most likely to close it, inside his hours, home-by time,
   daily limit and weekly cap. Minimums are only a tiebreaker on close calls.
2. **Ratings** update every run from each rep's certified close rate (rolling 30): New (first 90 days), Coaching,
   Tenured, Beast, and Lane (reps on the commercial lane). Each rating has its own daily max and weekly cap.
3. **Hot hand.** Any rep at Beast level (35%+ on the rolling 30, 15+ sits) is rated Beast whatever his start date,
   until he drops below 30%. State kept in `memory/hot.json`.
4. **The 7-a-week promise** is measured on a rolling quarter and scales with the schedule a rep makes available
   (full = 11 of every 14 days across the usual hours). Reps behind their own promise get a nudge on close calls.
   The promise is a floor, never a cap: reps who want more work are only limited by their daily max and weekly cap.
5. **New reps follow the Hero's Journey** (no leads in training, a light ramp) unless they are hot.
6. **Lanes** (set per rep on the Reps tab): commercial work only to commercial-lane reps, specialty to specialty-lane reps first with commercial-lane reps as backup, commercial-lane reps never on regular work.
7. **Bends** only to avoid leaving an appointment with nobody or to keep a same-day appointment. Never a 5th sit. Every
   bend is tagged and needs Richie's OK. Anything still stuck is "Nobody free" with the reasons.
8. **Routes**: every mile between back-to-back appointments, and half of each mile from where the rep starts, costs a little close chance (0.5 points per 10 miles, in `assignment_rules.json`). When plans are about equal on dollars, the one with less driving wins.
9. **Days off** come from the board (Reps tab and the "Working" checkboxes above the columns). `sync_roster.py` copies
   them into `assignment_rules.json` before each run.

Inside those rules it picks the plan with the most expected closes (close chance + same-day weight x same-day chance).
Every plan is saved to `memory/plans.csv` so it can be checked against what actually closed.

## How it learns and corrects itself

- **After every AccuLynx pull** (`run.py`): retrains on the newest data, scores every upcoming appointment, and saves
  what it predicted to `memory/predictions.csv`.
- **Every week** (`selftest.py`): for each recent month it trains only on sits before that month, predicts the month,
  and compares with what actually happened. It tries other settings and keeps one only if it predicts clearly better.
  It recalculates the same-day weight. Once 100+ of its own logged predictions have finished, it compares them with
  results and shifts future predictions if they ran high or low.
- **AI note reading** (`AI_NOTES.md`): Claude reads new lead notes and tags them. Any tag seen on 15+ sits becomes an
  input, and it only matters as much as results show it should.
- **After every run** (`outcomes.py`): for every appointment that already happened, logs the engine's pick, the board's
  pick after manager moves, who actually ran it in AccuLynx, the predicted odds for each, and whether it sat, sold and
  sold the same day. Late sales update the row on later runs. The weekly self-test reports close rate when the engine's
  pick ran the sit vs someone else vs a manager move, each against what was predicted.
- **Every week** (`learn.py`): the assignment logic tests itself live. Three dials decide how picks are made: how much
  extra a hot streak counts (`hot_boost_share`), how much driving counts (`route_close_points_per_10_miles`) and how much
  same-day signs count (`same_day_weight_scale`). One dial at a time gets a challenger value, used on alternating days
  (the other days keep the current value). Every finished sit is scored as sold minus how likely that lead was to close
  with anyone, so a tough day of leads does not count against a dial. When one side has 60+ sits and wins by 2+ points
  with real confidence (z 1.64), the winner becomes the new value; otherwise the current value stays. Each test runs at
  most 8 weeks, then the next dial in the queue gets tested. Guardrails: values stay inside each dial's range, and hard
  rules (hours, days off, lanes, daily limits, promises) are never touched. Set `learning.auto_promote` to false to make
  it propose changes only. Results go to `memory/experiments.csv`.
- Every change is written in plain words to `memory/learning_log.md`.

## Files

| File | What it is | Who changes it |
|---|---|---|
| `assignment_rules.json` | THE rules file: roster, hours, ratings, limits, lanes, bends | Joe (later the dashboard) |
| `settings.json` | Model settings: data window, note signal words, tuning | Joe |
| `engine.py` | The model | Code |
| `run.py` | Scores upcoming appointments, then builds the plan | Runs after each pull |
| `assign.py` | Hands out appointments by the rules | Called by run.py |
| `zip_centers.json` | Center point of each Long Island zip, for drive times | Code |
| `selftest.py` | Weekly test, retune, self-correction | Runs weekly |
| `learn.py` | Weekly live experiment on the assignment dials; keeps winners | Runs weekly after selftest.py |
| `sync_roster.py` | Copies the board's Reps tab and days off into the rules | Runs before each engine run |
| `board.py` | Builds board.json for the dashboard (cards, odds, money, map, results, forecast) | Runs after run.py |
| `dashboard/` | The board page (no customer data; board.json is built per run) | Code |
| `tests/test_rules.py` | Regression test: every hard rule holds in the current plan | Runs every engine run; exit 1 = broken |
| `tests/backtest_*.py` | Backtests behind engine changes, with results in their header | Rerun before changing the model |
| `AI_NOTES.md` | Instructions for Claude's note reading and weekly miss review | Joe |
| `memory/tuned.json` | Settings the engine picked for itself and its latest test results | The engine |
| `memory/learning_log.md` | What it learned and changed, in plain words | The engine |
| `memory/predictions.csv` | Every prediction it made, to check against results | The engine |
| `memory/plans.csv` | Every recommended assignment, to check against results | The engine |
| `memory/board_moves.csv` | Daily snapshot of manager moves and days off made on the board | `outcomes.py --save-board`, every run |
| `memory/outcomes.csv` | Every finished appointment: engine pick, board pick, who actually ran it, predicted odds for each, sat, sold, same day | `outcomes.py`, every run |
| `memory/experiments.csv` | Every finished assignment experiment: dial, values, sits each side, gain, verdict | `learn.py`, weekly |
| `memory/hot.json` | Which reps are currently hot | The engine |
| `memory/forecasts.csv` | What the board predicted for every upcoming day, each run (sales, $, same day, bookings still to come, full-team value) | `board.py`, every run |
| `memory/accuracy_daily.csv` | Each finished day: predicted vs actual appointments, sales, $ and same-day signs | `outcomes.py`, every run |
| `memory/note_tags.json` | AI tags for each lead's notes | Claude |

The engine reads the certified rules and the data. It never changes them.
