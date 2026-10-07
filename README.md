# rr-metrics-data

Private. Holds the newest Rapid Roofing AccuLynx reports for the **rr-metrics** Claude skill.

- `data/job_export_raw_latest.csv`: full job export (every lead, prospect, job, dead lead)
- `data/Revenue_In_Progress_latest.csv`: approved jobs with scheduled installs
- `data/status.json`: which AccuLynx run each file came from and when it was pulled

Every hour, `.github/workflows/pull.yml` checks the 5 daily AccuLynx schedules (6 AM, 9 AM, 12 PM, 3 PM, 6 PM), grabs the newest run of each report, and replaces the files. Only the latest copy is kept, so the repo stays small. If a pull fails, the last good files stay in place and GitHub emails the repo owner.

Needs the repo secret `ACCULYNX_API_KEY`.
