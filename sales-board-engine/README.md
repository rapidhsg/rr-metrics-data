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
| `settings.json` | Plain rules: data window, board reps, note signal words, what to test | Joe |
| `engine.py` | The model | Code |
| `run.py` | Scores upcoming appointments | Runs after each pull |
| `selftest.py` | Weekly test, retune, self-correction | Runs weekly |
| `AI_NOTES.md` | Instructions for Claude's note reading and weekly miss review | Joe |
| `memory/tuned.json` | Settings the engine picked for itself and its latest test results | The engine |
| `memory/learning_log.md` | What it learned and changed, in plain words | The engine |
| `memory/predictions.csv` | Every prediction it made, to check against results | The engine |
| `memory/note_tags.json` | AI tags for each lead's notes | Claude |

The engine reads the certified rules and the data. It never changes them.
