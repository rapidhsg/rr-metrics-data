// Feedback calls: every morning, load yesterday's quoted appointments that did not sign into GoHighLevel for Kelly to call.
//
// Who gets loaded: Initial Appointment Date = yesterday (Monday also picks up Saturday and Sunday), quoted
// (Primary Estimate Total > 0), Current Milestone = Prospect, and NOT submitted for approval. No Call Backs,
// no Service or Upsell / Change Order work types.
//
// For each one:
//   1. Get the customer's name, phone and email from AccuLynx.
//   2. Find them in GHL by phone, then email. If they aren't in GHL, create them the way our prospects are set up
//      (tag "prospect", lead source, trade type, job category, work type, address).
//   3. Fill the Feedback job fields and clear last time's answers.
//   4. Add the tag "feedback-call". That tag starts the "FC 1 - Start" workflow in GHL.
// A contact that already has this job and appointment date loaded is skipped, so running twice never double-loads.
//
// This is the only script in this repo that writes to GHL. It never writes to AccuLynx.
// Customer phone numbers and emails are never printed or saved here.
// Zero dependencies (Node 18+). Needs env ACCULYNX_API_KEY and GHL_FEEDBACK_TOKEN (GHL Private Integration
// "Feedback Calls": View Contacts, Edit Contacts, View Tags). DRY_RUN=1 shows what it would do without writing.
// FC_DATE=YYYY-MM-DD loads that appointment day instead of yesterday.
import { readFileSync } from "node:fs";
import { join } from "node:path";

const DIR = process.env.DATA_DIR || "data";
const ACX_KEY = process.env.ACCULYNX_API_KEY, GHL_KEY = process.env.GHL_FEEDBACK_TOKEN;
const LOCATION = process.env.GHL_LOCATION_ID || "snK6ntCH0DvCdvjyUt7D";   // Rapid Roofing & Gutters
const DRY = /^(1|true|yes)$/i.test(process.env.DRY_RUN || "");
if (!ACX_KEY || !GHL_KEY) { console.error("Missing ACCULYNX_API_KEY or GHL_FEEDBACK_TOKEN"); process.exit(1); }

// GHL contact custom field ids (Feedback Calls folder)
const F = {
  apptDate: "DubrvXCvwMOvyo28kkMC", rep: "6nsdUvNaBALF6eCnc4tO", estimate: "4i3u5qdz8CoFEkwxlJCR",
  jobId: "gG5Noz1yy3yoowHvPfBw", jobLink: "l15ivcgE0z6LvxVyPopY", repNotes: "82JoodsTGn6ixcT7LSOY",
};
// Kelly's answers from the last call, cleared each time a new feedback call is loaded
const ANSWERS = ["zNWVwtCCKOQ6Mv2tTO8E", "0JUYhK2FMYMlUnHTjCNh", "j0790m84QI9KaYlJuPwk", "rQdKaIzsQPYWDXTCPMZF",
  "asRnrt2Rk02kRaNkQpN4", "apW5ZnYtzJr774PzNuLf", "d4uP2nFfIMibDb7yKWZB", "RGuaLO0lnrDFq6UTBJXx"];
// Existing prospect fields, filled only when we create a new contact
const P = { workType: "4uIEVkycMtEzJmx40ypw", tradeTypes: "9md5GOC1ltXJhRJ23yNr", jobCategory: "WFnMkufqCpLBZ5CGUySd" };
const TRADE_OPTIONS = ["Roofing", "Designer Roofing", "Siding", "Gutters", "Windows", "Other"];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function call(url, { method = "GET", headers, body, allow404 = false } = {}) {
  let last;
  for (let i = 0; i < 5; i++) {
    const res = await fetch(url, { method, headers: { ...headers, ...(body ? { "Content-Type": "application/json" } : {}) }, body: body ? JSON.stringify(body) : undefined });
    if (res.ok) { const t = await res.text(); return t ? JSON.parse(t) : {}; }
    if (res.status === 404 && allow404) return null;
    last = `HTTP ${res.status} on ${method} ${url.split("?")[0]}: ${(await res.text().catch(() => "")).slice(0, 200)}`;
    if (res.status !== 429 && res.status < 500) break;
    await sleep(1500 * 2 ** i);
  }
  throw new Error(last);
}
const ACX = "https://api.acculynx.com/api/v2";
const acx = (p, o) => call(p.startsWith("http") ? p : ACX + p, { ...o, headers: { Authorization: `Bearer ${ACX_KEY}`, Accept: "application/json" } });
const GHL = "https://services.leadconnectorhq.com";
const ghl = (p, o = {}) => call(GHL + p, { ...o, headers: { Authorization: `Bearer ${GHL_KEY}`, Version: "2021-07-28", Accept: "application/json" } });

// ---------- CSV (same repair logic as scripts/calls.mjs: AccuLynx doesn't quote notes with line breaks) ----------
function parseCsv(text) {
  const rows = []; let row = [], f = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) { if (c === '"') { if (text[i + 1] === '"') { f += '"'; i++; } else q = false; } else f += c; }
    else if (c === '"' && f === "") q = true;
    else if (c === ",") { row.push(f); f = ""; }
    else if (c === "\n" || c === "\r") { if (c === "\r" && text[i + 1] === "\n") i++; row.push(f); rows.push(row); row = []; f = ""; }
    else f += c;
  }
  if (f || row.length) { row.push(f); rows.push(row); }
  const head = (rows.shift() || []).map((h) => h.replace(/^﻿/, "").trim()), n = head.length;
  const k = Math.max(0, head.findIndex((h) => /note/i.test(h))), tail = n - 1 - k, recs = [];
  let cur = null;
  for (const r of rows) {
    if (!cur) cur = r.slice();
    else { cur[cur.length - 1] += "\n" + (r[0] ?? ""); cur.push(...r.slice(1)); }
    if (cur.length >= n) {
      if (cur.length > n) cur = [...cur.slice(0, k), cur.slice(k, cur.length - tail).join(","), ...cur.slice(cur.length - tail)];
      recs.push(cur); cur = null;
    }
  }
  return recs.map((r) => Object.fromEntries(head.map((h, i) => [h, r[i] ?? ""])));
}
const acxDay = (s) => {   // "10/14/26 9:00 AM" -> "2026-10-14"
  const m = String(s || "").match(/(\d{1,2})\/(\d{1,2})\/(\d{2,4})/);
  if (!m) return null;
  const y = +m[3] < 100 ? 2000 + +m[3] : +m[3];
  return `${y}-${String(m[1]).padStart(2, "0")}-${String(m[2]).padStart(2, "0")}`;
};
const num = (v) => { const x = parseFloat(String(v || "").replace(/[$,\s]/g, "")); return Number.isFinite(x) ? x : 0; };
const digits10 = (p) => { const d = String(p || "").replace(/\D/g, ""); return d.length >= 10 ? d.slice(-10) : null; };

// ---------- which appointment days to load ----------
const nyNow = new Date(new Date().toLocaleString("en-US", { timeZone: "America/New_York" }));
if (!process.env.FC_DATE && process.env.GITHUB_EVENT_NAME === "schedule" && nyNow.getHours() < 8) {
  console.log("Before 8 AM Eastern, skipping (the next scheduled run will do it)"); process.exit(0);
}
const isoDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const back = (n) => { const d = new Date(nyNow); d.setDate(d.getDate() - n); return isoDay(d); };
const days = process.env.FC_DATE ? [process.env.FC_DATE] : nyNow.getDay() === 1 ? [back(2), back(1)] : [back(1)];   // Monday: Sat + Sun
console.log(`Loading feedback calls for appointments on ${days.join(", ")}${DRY ? " (DRY RUN, nothing written)" : ""}`);

const jobs = parseCsv(readFileSync(join(DIR, "job_export_raw_latest.csv"), "utf8")).filter((r) =>
  days.includes(acxDay(r["Initial Appointment Date"])) &&
  num(r["Primary Estimate Total"]) > 0 &&
  r["Current Milestone"] === "Prospect" &&
  !String(r["Submitted for Approval Date"] || "").trim() &&
  !/Call Back/i.test(r["Job Trade Type"] || "") &&
  !["Service", "Upsell / Change Order"].includes(r["Work Type"] || ""));
console.log(`${jobs.length} quoted, not sold, not submitted`);

// ---------- AccuLynx: primary contact's name, phones, emails ----------
async function acxContact(guid) {
  const list = await acx(`/jobs/${guid}/contacts?includes=contact`, { allow404: true });
  const items = (list?.items || []).filter((x) => x.contact?.id);
  const pick = items.find((x) => x.isPrimary || x.primary) || items[0];
  if (!pick) return null;
  const c = await acx(`/contacts/${pick.contact.id}`, { allow404: true });
  if (!c) return null;
  const phones = [], emails = [];
  for (const p of c.phoneNumbers || []) {
    const v = p.number ?? (p._link ? (await acx(p._link, { allow404: true }))?.number : null);
    if (digits10(v)) phones.push(digits10(v));
  }
  for (const e of c.emailAddresses || []) {
    const v = e.address ?? (e._link ? (await acx(e._link, { allow404: true }))?.address : null);
    if (v && String(v).includes("@")) emails.push(String(v).trim().toLowerCase());
  }
  return { first: c.firstName || "", last: c.lastName || "", phones, emails };
}

// ---------- GHL: find by phone, then email ----------
async function findContact(phones, emails) {
  for (const p of phones) {
    const r = await ghl(`/contacts/search/duplicate?locationId=${LOCATION}&number=${encodeURIComponent("+1" + p)}`, { allow404: true });
    if (r?.contact?.id) return r.contact.id;
  }
  for (const e of emails) {
    const r = await ghl(`/contacts/search/duplicate?locationId=${LOCATION}&email=${encodeURIComponent(e)}`, { allow404: true });
    if (r?.contact?.id) return r.contact.id;
  }
  return null;
}

let loaded = 0, created = 0, skipped = 0;
const problems = [];
for (const j of jobs) {
  const guid = ((j["Job Number Url"] || "").match(/jobs\/([0-9a-f-]{36})/) || [])[1];
  const who = `${j["Primary Contact: Name"] || "?"} (${j["Primary Salesperson"] || "no rep"})`;
  if (!guid) { problems.push(`${who}: no AccuLynx job link`); continue; }
  const link = `https://my.acculynx.com/jobs/${guid}`;
  try {
    const ac = await acxContact(guid);
    if (!ac || (!ac.phones.length && !ac.emails.length)) { problems.push(`${who}: no phone or email in AccuLynx ${link}`); continue; }

    let id = await findContact(ac.phones, ac.emails), isNew = false;
    if (id) {
      const cur = (await ghl(`/contacts/${id}`))?.contact;
      const val = (fid) => (cur?.customFields || []).find((x) => x.id === fid)?.value;
      if (val(F.jobId) === guid && String(val(F.apptDate) || "").slice(0, 10) === acxDay(j["Initial Appointment Date"]) && (cur?.tags || []).length) {
        skipped++; console.log(`skip (already loaded): ${who}`); continue;
      }
    }
    const notes = [j["POST APPOINTMENT NOTES #1"], j["POST APPOINTMENT NOTES #2"]].map((s) => String(s || "").trim()).filter(Boolean).join("\n\n");
    const fields = [
      { id: F.apptDate, field_value: acxDay(j["Initial Appointment Date"]) },
      { id: F.rep, field_value: j["Primary Salesperson"] || "" },
      { id: F.estimate, field_value: num(j["Primary Estimate Total"]) },
      { id: F.jobId, field_value: guid },
      { id: F.jobLink, field_value: link },
      { id: F.repNotes, field_value: notes },
      ...ANSWERS.map((fid) => ({ id: fid, field_value: "" })),
    ];

    if (!id) {
      const trades = String(j["Job Trade Type"] || "").split(/[,;]/).map((s) => s.trim()).filter((t) => TRADE_OPTIONS.includes(t));
      const body = {
        locationId: LOCATION, firstName: ac.first, lastName: ac.last,
        phone: ac.phones[0] ? "+1" + ac.phones[0] : undefined, email: ac.emails[0] || undefined,
        address1: j["Job: Location Street 1"] || undefined, city: j["Job: Location City"] || undefined,
        postalCode: String(j["Job: Location Zip Code"] || "") || undefined, state: "NY", country: "US",
        source: j["Sub Lead Source"] || j["Parent Lead Source"] || "AccuLynx", tags: ["prospect"],
        customFields: [
          ...fields,
          ...(["New", "Repair", "Inspection"].includes(j["Work Type"]) ? [{ id: P.workType, field_value: j["Work Type"] }] : []),
          ...(trades.length ? [{ id: P.tradeTypes, field_value: trades }] : []),
          ...(["Residential", "Commercial"].includes(j["Job Category"]) ? [{ id: P.jobCategory, field_value: [j["Job Category"]] }] : []),
        ],
      };
      if (DRY) { console.log(`would create + load: ${who}`); created++; loaded++; continue; }
      id = (await ghl(`/contacts/`, { method: "POST", body }))?.contact?.id;
      if (!id) throw new Error("create returned no contact id");
      isNew = true; created++;
    } else {
      if (DRY) { console.log(`would load: ${who}`); loaded++; continue; }
      await ghl(`/contacts/${id}`, { method: "PUT", body: { customFields: fields } });
    }
    // Remove then add the tag so the workflow fires even if an old feedback-call tag was left on
    await ghl(`/contacts/${id}/tags`, { method: "DELETE", body: { tags: ["feedback-call"] } }).catch(() => null);
    await ghl(`/contacts/${id}/tags`, { method: "POST", body: { tags: ["feedback-call"] } });
    loaded++;
    console.log(`${isNew ? "created + loaded" : "loaded"}: ${who}`);
  } catch (e) {
    problems.push(`${who}: ${e.message} ${link}`);
    if (/HTTP 401|HTTP 403/.test(e.message)) break;   // bad key: stop instead of failing every row
  }
}

console.log(`Done: ${loaded} loaded (${created} new contacts), ${skipped} already loaded, ${problems.length} problems`);
if (problems.length) {
  console.error("Problems (Kelly can still call these from AccuLynx):\n" + problems.join("\n"));
  process.exit(1);   // red X in Actions + GitHub emails the repo owner
}
