# rr-metrics-data

Private. The brain and the data behind the **rr-metrics** Claude skill.

## The rules (main branch). Only Joe changes these, directly on github.com.

- `rules/RULES.md`: what every metric means and how Claude must answer.
- `rules/settings.json`: the exact lists the math uses (sales team roster, dead reasons, work types, and so on). Names must match AccuLynx exactly.
- `rules/rr_metrics.py`: the calculation code. Reads settings.json.

Every chat that uses the skill reads these files fresh, so a change here applies to everyone right away. No skill re-upload needed.

**After any change**, open the **Actions** tab. `check-rules` runs automatically:
- Green check: the rules still work.
- Red X: the change broke something, usually a misspelled name. Fix or undo the change.

GitHub keeps the full history of every change (who, what, when) under **Commits**.

## The data (data branch). Updated automatically, never by hand.

- `data/job_export_raw_latest.csv`: full job export (every lead, prospect, job, dead lead)
- `data/Revenue_In_Progress_latest.csv`: approved jobs with scheduled installs
- `data/job_expenses_latest.csv`: every cost line on Closed jobs (last 12 months), for job costing
- `data/status.json`: which AccuLynx run each file came from and when it was pulled

Every 15 minutes, `pull-acculynx-reports` checks the 5 daily AccuLynx schedules (6 AM, 9 AM, 12 PM, 3 PM, 6 PM), grabs the newest run of each report, and replaces the files on the `data` branch. Only the latest copy is kept. If a pull fails, the last good files stay in place and GitHub emails the repo owner. To pull right away: Actions > pull-acculynx-reports > Run workflow.

Needs the repo secret `ACCULYNX_API_KEY`.

## Setter call transcripts (data branch, data/calls/)

Every pull also matches the CSRs' calls in GoHighLevel to AccuLynx jobs, so every booked appointment can be read next to how it was set.
- `data/calls/jobs/<RR number>.json`: one file per job with an appointment. How it was matched, the setter, every call with the customer from the lead up to the appointment, which call booked it, and the transcripts. Jobs without an RR number yet use their AccuLynx job id; the file is renamed when the job gets one.
- `data/calls/index.csv`: one row per job, matched or not. `data/calls/unmatched.csv`: jobs with no match and what was tried.
- Matching uses every field: RR number in GHL custom fields, phone, email, then name near the lead date. The first run goes back 120 days and fills in over a few runs.
- Customer phone numbers and emails are only used to match and are kept as one-way hashes. They are removed from the transcript text, along with street addresses.

Needs the repo secret `GHL_API_KEY`: a GoHighLevel Private Integration token for the Rapid Roofing & Gutters location with read access to contacts, conversations, conversation messages and users. Without it the step skips.

## Tools that read from this repo

This repo holds only the data and the rules. Tools live in their own repos and only read from here:
- **rapidhsg/dashboard-engine**: RR1 and RR2 dashboards
- **rapidhsg/sales-board-engine**: sales board and appointment assignment engine (moved out of this repo on 2026-10-13)

No tool pulls AccuLynx on its own or defines a metric. New metrics are added here first.
