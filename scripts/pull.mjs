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

// 3b. Ad platform data from Windsor.ai: daily spend and results per campaign (Meta and Google Ads).
const windsorKeyAds = process.env.WINDSOR_API_KEY;
if (windsorKeyAds) {
  try {
    const from = new Date(Date.now() - 400 * 864e5).toISOString().slice(0, 10);
    const to = new Date().toISOString().slice(0, 10);
    const sources = [
      { platform: "Meta", connector: "facebook", leads: "actions_lead" },
      { platform: "Google Ads", connector: "google_ads", leads: "conversions" },
    ];
    const q = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const lines = [];
    for (const src of sources) {
      const url = `https://connectors.windsor.ai/${src.connector}?api_key=${windsorKeyAds}&date_from=${from}&date_to=${to}` +
        `&fields=date,campaign,spend,impressions,clicks,${src.leads}`;
      const body = await get(url, { auth: false });
      const rows = Array.isArray(body) ? body : body.data || body.result || [];
      for (const r of rows) {
        if (!r.date) continue;
        lines.push([r.date, src.platform, r.campaign, r.spend ?? 0, r.impressions ?? 0, r.clicks ?? 0, r[src.leads] ?? 0].map(q).join(","));
      }
    }
    lines.sort();
    const csv = "date,platform,campaign,spend,impressions,clicks,platform_leads\n" + lines.join("\n") + "\n";
    const out = join(DIR, "ads_daily_latest.csv");
    const old = existsSync(out) ? readFileSync(out, "utf8") : "";
    if (lines.length && csv !== old) {
      writeFileSync(out, csv);
      status.ads = { pulledAt: new Date().toISOString(), rows: lines.length, from, to, file: "data/ads_daily_latest.csv" };
      changed = true;
      console.log(`ads: saved ${lines.length} daily campaign rows`);
    } else console.log(`ads: no change (${lines.length} rows)`);
  } catch (err) {
    problems.push(`ads: ${err.message.replace(windsorKeyAds, "***")}`);
  }
}

// 3. Google reviews from Windsor.ai (all Google Business Profile locations), all time: id, date, stars, location,
//    reviewer name (as shown on Google), review text and our reply. Phone numbers and emails are blanked out of the text.
const windsorKey = process.env.WINDSOR_API_KEY;
if (windsorKey) {
  try {
    const from = "2010-01-01"; // all time (Google shows 855 reviews across the 5 profiles)
    const to = new Date().toISOString().slice(0, 10);
    const url = `https://connectors.windsor.ai/google_my_business?api_key=${windsorKey}&date_from=${from}&date_to=${to}` +
      `&fields=review_id,review_create_time,review_star_rating,location_address_locality,review_reviewer,review_comment,review_reply_comment`;
    const body = await get(url, { auth: false });
    const rows = (Array.isArray(body) ? body : body.data || body.result || []).filter((r) => r.review_id);
    const stars = { ONE: 1, TWO: 2, THREE: 3, FOUR: 4, FIVE: 5 };
    const q = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const scrub = (t) => String(t ?? "")
      .replace(/[\w.+-]+@[\w-]+\.[\w.]+/g, "[email removed]")
      .replace(/\(?\b\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b/g, "[phone removed]");
    const csv = "review_id,created_utc,stars,location,reviewer,text,reply\n" + rows
      .sort((x, y) => String(x.review_create_time).localeCompare(String(y.review_create_time)))
      .map((r) => [r.review_id, r.review_create_time, stars[r.review_star_rating] ?? r.review_star_rating, r.location_address_locality,
        r.review_reviewer, scrub(r.review_comment), scrub(r.review_reply_comment)].map(q).join(","))
      .join("\n") + "\n";
    const out = join(DIR, "google_reviews_latest.csv");
    const old = existsSync(out) ? readFileSync(out, "utf8") : "";
    if (rows.length && csv !== old) {
      writeFileSync(out, csv);
      status.google_reviews = { pulledAt: new Date().toISOString(), rows: rows.length, from, to, file: "data/google_reviews_latest.csv" };
      changed = true;
      console.log(`google_reviews: saved ${rows.length} reviews`);
    } else console.log(`google_reviews: no change (${rows.length} reviews)`);
  } catch (err) {
    problems.push(`google_reviews: ${err.message.replace(windsorKey, "***")}`);
  }
}

if (JSON.stringify(status.schedules) !== JSON.stringify(seen)) { status.schedules = seen; changed = true; }
for (const [label, v] of Object.entries(seen)) console.log(`${label}: latest run ${v.runDate}, files: ${v.files.join(", ") || "none"}`);
if (changed) writeFileSync(statusPath, JSON.stringify(status, null, 2) + "\n");
writeFileSync(process.env.GITHUB_OUTPUT || "/dev/null", `changed=${changed}\n`, { flag: "a" });
if (problems.length) { console.error("Problems:\n" + problems.join("\n")); process.exit(1); }
