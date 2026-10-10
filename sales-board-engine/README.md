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
change there is the only change needed. (When the dashboard's Reps & Availability tab is live, it will own the roster.)

How it works, in words:

1. **Ratings** update every run from each rep's certified close rate (rolling 30): New (first 90 days), Coaching,
   Tenured, Beast, and Lane (Meinardus). Each rating has its own daily max, weekly minimum and weekly cap.
2. **New reps follow the Hero's Journey**: no leads in training, a light ramp, then full volume after the Day 29
   checkpoint, or capped with no minimum and flagged for management review if they are under the checkpoint.
3. **Weekly order**: fill minimums first (reps behind on the yearly promise get priority), then feed the beasts:
   extra appointments go to the best close chance up to each cap. Specialty sits do not count toward the week.
4. **Lanes**: commercial to Meinardus only, specialty to Francesco with Meinardus as backup, no Meinardus on regular work.
5. **Bends** only to avoid leaving an appointment with nobody or to keep a same-day appointment. Never a 5th sit. Every
   bend is tagged and needs Richie's OK. Anything still stuck is "Nobody free" with the reasons.
6. **Speed**: when a lead that came in today is booked for a later day and a fitting rep is free today, the plan says so.

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
| `AI_NOTES.md` | Instructions for Claude's note reading and weekly miss review | Joe |
| `memory/tuned.json` | Settings the engine picked for itself and its latest test results | The engine |
| `memory/learning_log.md` | What it learned and changed, in plain words | The engine |
| `memory/predictions.csv` | Every prediction it made, to check against results | The engine |
| `memory/plans.csv` | Every recommended assignment, to check against results | The engine |
| `memory/note_tags.json` | AI tags for each lead's notes | Claude |

The engine reads the certified rules and the data. It never changes them.
