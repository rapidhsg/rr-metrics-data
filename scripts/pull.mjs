// Pulls the newest AccuLynx job export and Revenue In Progress report into data/.
// Checks all 5 daily schedules and keeps the most recent run of each report.
// Zero dependencies (Node 18+). Needs env ACCULYNX_API_KEY.
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { join } from "node:path";

// Where to write the files (the workflow points this at a checkout of the data branch).
const DIR = process.env.DATA_DIR || "data";

const BASE = "https://api.acculynx.com/api/v2";
const SCHEDULES = {
  "36240e2e-28d3-443f-b14e-506ea7937958": "6 AM",
  "d61c0acc-ac2e-4387-98af-19c8fa7bc452": "9 AM",
  "bb9cdf02-23dc-4786-a737-6ce24bf8f544": "12 PM",
  "1f40b3e4-d5b9-44b9-a3d8-ea2e4944860c": "3 PM",
  "eb210542-a25f-4c21-b7b6-04b25aefd9d4": "6 PM",
};
// Report file name prefix (as AccuLynx names it) -> saved file + a column that must be present.
const REPORTS = {
  job_export_raw: { out: "job_export_raw_latest.csv", mustHave: "Current Milestone" },
  revenue_in_progress: { out: "Revenue_In_Progress_latest.csv", mustHave: "Crew End Date" },
  job_expenses_raw: { out: "job_expenses_latest.csv", mustHave: "," },
};

const key = process.env.ACCULYNX_API_KEY;
if (!key) { console.error("Missing ACCULYNX_API_KEY"); process.exit(1); }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function get(url, { auth = true, json = true, allow404 = false } = {}) {
  let last;
  for (let i = 0; i < 4; i++) {
    const res = await fetch(url, auth ? { headers: { Authorization: `Bearer ${key}`, Accept: "application/json" } } : {});
    if (res.ok) return json ? res.json() : res.text();
    if (res.status === 404 && allow404) return null;
    last = `HTTP ${res.status} on ${url.split("?")[0]}`;
    if (res.status !== 429 && res.status < 500) break;
    await sleep(1000 * 2 ** i);
  }
  throw new Error(last);
}

const statusPath = join(DIR, "status.json");
const status = existsSync(statusPath) ? JSON.parse(readFileSync(statusPath, "utf8")) : {};

// 1. Find the newest file for each report across all schedules.
const best = {};
const seen = {}; // what each schedule last delivered, saved to status.json so problems are easy to spot
for (const [id, label] of Object.entries(SCHEDULES)) {
  const latest = await get(`${BASE}/reports/scheduled-reports/${id}/runs/latest`, { allow404: true });
  if (!latest?.runInstanceId) { console.log(`${label}: no run yet`); seen[label] = { runDate: null, files: [] }; continue; }
  const rec = await get(`${BASE}/reports/scheduled-reports/${id}/runs/${latest.runInstanceId}/recipients`);
  seen[label] = { runDate: latest.date, files: [] };
  for (const item of rec?.items || []) {
    for (const f of item.files || []) {
      const name = decodeURIComponent((f.fileUrl || "").split("?")[0].split("/").pop()).toLowerCase();
      if (!seen[label].files.includes(name)) seen[label].files.push(name);
      const prefix = Object.keys(REPORTS).find((p) => name.startsWith(p));
      if (prefix && (!best[prefix] || String(latest.date) > String(best[prefix].runDate))) {
        best[prefix] = { url: f.fileUrl, runDate: latest.date, schedule: label };
      }
    }
  }
}

// 2. Download and save each report, but only if it is a newer run. Never overwrite with a bad file.
mkdirSync(DIR, { recursive: true });
let changed = false;
const problems = [];
for (const [prefix, cfg] of Object.entries(REPORTS)) {
  const pick = best[prefix];
  if (!pick) { problems.push(`${prefix}: no schedule has delivered it`); continue; }
  if (status[prefix]?.runDate === pick.runDate) { console.log(`${prefix}: already have run ${pick.runDate}`); continue; }
  const csv = await get(pick.url, { auth: false, json: false });
  const lines = csv.split("\n").length;
  if (lines < 3 || !csv.slice(0, 2000).includes(cfg.mustHave)) { problems.push(`${prefix}: downloaded file looks wrong (${lines} lines)`); continue; }
  writeFileSync(join(DIR, cfg.out), csv);
  status[prefix] = { runDate: pick.runDate, schedule: pick.schedule, pulledAt: new Date().toISOString(), rows: lines - 2, file: "data/" + cfg.out };
  changed = true;
  console.log(`${prefix}: saved run ${pick.runDate} (${pick.schedule}), ${lines - 2} rows`);
}

if (JSON.stringify(status.schedules) !== JSON.stringify(seen)) { status.schedules = seen; changed = true; }
for (const [label, v] of Object.entries(seen)) console.log(`${label}: latest run ${v.runDate}, files: ${v.files.join(", ") || "none"}`);
if (changed) writeFileSync(statusPath, JSON.stringify(status, null, 2) + "\n");
writeFileSync(process.env.GITHUB_OUTPUT || "/dev/null", `changed=${changed}\n`, { flag: "a" });
if (problems.length) { console.error("Problems:\n" + problems.join("\n")); process.exit(1); }
