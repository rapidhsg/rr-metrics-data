#!/usr/bin/env bash
# One full engine run, used by the scheduled task. Stops at the first failure.
# Usage: bash scheduled_run.sh <data dir with job_export_raw_latest.csv and status.json> <board export dir with roster/ and cards/> <out dir> [weekly]
#   board export dir: one JSON file per board database doc (roster/<slug>.json, cards/<guid>.json), each the doc's data.
#   weekly: also run the self-test and the assignment experiment review (learn.py).
set -euo pipefail
export TZ=America/New_York   # appointment times are Eastern; "now" and "today" must be too
cd "$(dirname "$0")"
DATA="$1"; EXPORT="$2"; OUT="$3"; WEEKLY="${4:-}"
CSV="$DATA/job_export_raw_latest.csv"
mkdir -p "$OUT" "$EXPORT/roster" "$EXPORT/cards"
python sync_roster.py "$EXPORT/roster"
python outcomes.py --save-board "$EXPORT/cards"
python run.py "$CSV" "$OUT"
python board.py "$OUT" "$CSV" "$DATA/status.json"
python tests/test_rules.py "$CSV" "$OUT"
python outcomes.py "$CSV"
if [ "$WEEKLY" = "weekly" ]; then
  python selftest.py "$CSV"
  python learn.py
fi
find .. -name __pycache__ -not -path "../.git/*" -exec rm -rf {} + 2>/dev/null || true
echo "scheduled run OK"
