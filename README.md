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
