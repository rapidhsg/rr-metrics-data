// Setter call transcripts, matched to AccuLynx jobs (RR numbers).
// For every job with an appointment set, find the customer's calls in GoHighLevel (the phone system the CSRs use),
// pick the call where the appointment was set, and save the transcripts in their own file per job:
//   data/calls/jobs/<RR number>.json   one file per job: how it matched, the setter, every call, transcripts
//                                      (jobs without an RR number yet use the AccuLynx job id; the file is renamed once it gets one)
//   data/calls/index.csv               one row per job (matched or not), for quick lookups
//   data/calls/unmatched.csv           jobs we could not match, and what we tried
// Matching uses every field we have: RR number (in GHL custom fields), phone, email, then name near the lead date.
// Customer phone numbers and emails are only used to match: they are stored as one-way hashes, and are removed
// (with street addresses) from the transcript text. Nothing here ever writes to AccuLynx or GHL.
// Zero dependencies (Node 18+). Needs env ACCULYNX_API_KEY and GHL_API_KEY (a GHL Private Integration token with
// contacts.readonly, conversations.readonly, conversations/message.readonly, users.readonly). Without GHL_API_KEY it skips.
import { readFileSync, writeFileSync, mkdirSync, existsSync, rmSync } from "node:fs";
import { join } from "node:path";
import { createHash } from "node:crypto";

const DIR = process.env.DATA_DIR || "data";
const OUT = join(DIR, "calls");
const GHL_KEY = process.env.GHL_API_KEY, ACX_KEY = process.env.ACCULYNX_API_KEY;
const LOCATION = process.env.GHL_LOCATION_ID || "snK6ntCH0DvCdvjyUt7D";   // Rapid Roofing & Gutters
const BACKFILL_DAYS = +(process.env.CALLS_BACKFILL_DAYS || 120);   // how far back to match jobs
const MAX_JOBS = +(process.env.CALLS_MAX_JOBS || 150);             // AccuLynx lookups per run (backfill fills in over a few runs)
const MAX_TRANSCRIPTS = +(process.env.CALLS_MAX_TRANSCRIPTS || 400);
const out = (k, v) => writeFileSync(process.env.GITHUB_OUTPUT || "/dev/null", `${k}=${v}\n`, { flag: "a" });

if (!GHL_KEY) { console.log("calls: GHL_API_KEY not set, skipping"); out("calls_changed", "false"); process.exit(0); }
if (!ACX_KEY) { console.log("calls: ACCULYNX_API_KEY not set, skipping"); out("calls_changed", "false"); process.exit(0); }

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function get(url, headers, { allow404 = false } = {}) {
  let last;
  for (let i = 0; i < 5; i++) {
    const res = await fetch(url, { headers });
    if (res.ok) return res.json();
    if (res.status === 404 && allow404) return null;
    last = `HTTP ${res.status} on ${url.split("?")[0]}`;
    if (res.status !== 429 && res.status < 500) break;
    await sleep(1500 * 2 ** i);
  }
  throw new Error(last);
}
const GHL = "https://services.leadconnectorhq.com";
const ghl = (path, version = "2021-04-15", opts) => get(GHL + path, { Authorization: `Bearer ${GHL_KEY}`, Version: version, Accept: "application/json" }, opts);
const ACX = "https://api.acculynx.com/api/v2";
const acx = (pathOrUrl, opts) => get(pathOrUrl.startsWith("http") ? pathOrUrl : ACX + pathOrUrl, { Authorization: `Bearer ${ACX_KEY}`, Accept: "application/json" }, opts);

// ---------- small helpers ----------
const hash = (v) => v ? createHash("sha256").update("rr|" + v).digest("hex").slice(0, 24) : null;
const digits10 = (p) => { const d = String(p || "").replace(/\D/g, ""); return d.length >= 10 ? d.slice(-10) : null; };
const normEmail = (e) => { const s = String(e || "").trim().toLowerCase(); return s.includes("@") ? s : null; };
const normName = (n) => String(n || "").toLowerCase().replace(/[^a-z ]/g, " ").split(/\s+/).filter(Boolean).join(" ");
const nameKeys = (n) => { const w = normName(n).split(" ").filter((x) => !["and", "mr", "mrs", "ms", "dr", "jr", "sr"].includes(x)); return w.length >= 2 ? [w[0] + " " + w[w.length - 1]] : []; };
const loadJson = (f, d) => existsSync(join(OUT, f)) ? JSON.parse(readFileSync(join(OUT, f), "utf8")) : d;
const saveJson = (f, v) => writeFileSync(join(OUT, f), JSON.stringify(v, null, 1) + "\n");
const day = (d) => (d ? new Date(d).toISOString().slice(0, 10) : null);

function parseCsv(text) {   // RFC 4180: quotes, commas and line breaks inside fields
  const rows = []; let row = [], f = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) { if (c === '"') { if (text[i + 1] === '"') { f += '"'; i++; } else q = false; } else f += c; }
    else if (c === '"' && f === "") q = true;   // a quote only opens a quoted field at its start (like Python's csv)
    else if (c === ",") { row.push(f); f = ""; }
    else if (c === "\n" || c === "\r") { if (c === "\r" && text[i + 1] === "\n") i++; row.push(f); rows.push(row); row = []; f = ""; }
    else f += c;
  }
  if (f || row.length) { row.push(f); rows.push(row); }
  const head = (rows.shift() || []).map((h) => h.replace(/^\uFEFF/, "").trim()), n = head.length;
  // AccuLynx doesn't quote notes that hold line breaks or commas, so one record can spill over several lines.
  // Glue the pieces back together the same way the rules do (rules/rr_metrics.py _repaired_csv).
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
const acxDate = (s) => {   // "10/14/26 9:00 AM" or "10/14/26"
  const m = String(s || "").match(/(\d{1,2})\/(\d{1,2})\/(\d{2,4})(?:\s+(\d{1,2}):(\d{2})\s*([AP]M))?/i);
  if (!m) return null;
  let [, mo, d, y, h = "0", mi = "0", ap] = m; y = +y < 100 ? 2000 + +y : +y; h = +h % 12 + (ap && /pm/i.test(ap) ? 12 : 0);
  return new Date(Date.UTC(y, mo - 1, d, h + 4, +mi));   // Eastern, close enough for matching by day
};

// Remove customer contact details from transcript text: emails, phone numbers, street addresses, long digit runs.
const STREET = "(?:avenue|ave|street|st|road|rd|lane|ln|drive|dr|court|ct|place|pl|boulevard|blvd|way|terrace|ter|circle|cir|highway|hwy|parkway|pkwy|turnpike|tpke|path|trail|loop|plaza)";
function scrub(t) {
  return String(t || "")
    .replace(/[\w.+-]+\s*(?:@|at)\s*(?:gmail|yahoo|hotmail|aol|outlook|icloud|optonline|verizon|msn|live|me)\s*(?:\.|dot)\s*(?:com|net)/gi, "[email removed]")
    .replace(/[\w.+-]+@[\w-]+\.[\w.]+/g, "[email removed]")
    .replace(/\(?\b\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b/g, "[phone removed]")
    .replace(new RegExp(`\\b\\d{1,6}[a-z]?\\s+(?:[A-Za-z]+\\s+){1,3}${STREET}\\b\\.?`, "gi"), "[address removed]")
    .replace(/\b\d{5,}\b/g, "[number removed]");
}

// ---------- state ----------
mkdirSync(join(OUT, "jobs"), { recursive: true });
const state = loadJson("_state.json", { calls_synced_to: null });
const ghlCalls = loadJson("_ghl_calls.json", {});        // message id -> {c: contact, t: time, s: seconds, d: direction, u: user}
const ghlContacts = loadJson("_ghl_contacts.json", {});  // contact id -> {n: name keys, ph: [hash], em: [hash], rr: [RR numbers], at: added}
const ghlUsers = loadJson("_ghl_users.json", {});        // user id -> name
const acxContacts = loadJson("_acx_contacts.json", {});  // RR -> {ph: [hash], em: [hash], at: checked}
const index = loadJson("_index.json", {});               // RR -> summary row
let changed = false, problems = [];

// ---------- 1. GHL: every call since we last looked (the first run goes back BACKFILL_DAYS) ----------
const since = state.calls_synced_to || new Date(Date.now() - (BACKFILL_DAYS + 30) * 864e5).toISOString();
const until = new Date().toISOString();
let cursor = null, newCalls = 0;
try {
  do {
    const qs = new URLSearchParams({ locationId: LOCATION, channel: "Call", startDate: since, endDate: until, limit: "100", sortBy: "createdAt", sortOrder: "asc" });
    if (cursor) qs.set("cursor", cursor);
    const page = await ghl(`/conversations/messages/export?${qs}`);
    for (const m of page.messages || []) {
      if (!m.id || !m.contactId || ghlCalls[m.id]) continue;
      ghlCalls[m.id] = { c: m.contactId, t: m.dateAdded, s: m.meta?.call?.duration ?? null, d: m.direction, u: m.userId || null, st: m.meta?.call?.status || m.status || null };
      newCalls++;
    }
    cursor = page.nextCursor || null;
  } while (cursor);
  state.calls_synced_to = until;
  console.log(`calls: ${newCalls} new GHL calls (${Object.keys(ghlCalls).length} known)`);
} catch (e) { problems.push(`GHL call list: ${e.message}`); }

// GHL contact details for any contact we haven't looked up yet: names, hashed phones and emails, and any RR number in custom fields
const needContacts = [...new Set(Object.values(ghlCalls).map((x) => x.c))].filter((c) => !ghlContacts[c]);
for (const id of needContacts) {
  try {
    const r = await ghl(`/contacts/${id}`, "2021-07-28", { allow404: true });
    const c = r?.contact || {};
    const phones = [c.phone, ...(c.additionalPhones || []).map((p) => p.phone || p)].map(digits10).filter(Boolean);
    const emails = [c.email, ...(c.additionalEmails || []).map((e) => e.email || e)].map(normEmail).filter(Boolean);
    const rr = JSON.stringify(c.customFields || []).match(/RR-?\d{3,6}/gi) || [];
    ghlContacts[id] = { n: nameKeys(c.contactName || `${c.firstName || ""} ${c.lastName || ""}`), ph: phones.map(hash), em: emails.map(hash), rr: [...new Set(rr.map((x) => x.toUpperCase().replace(/^RR-?/, "RR-")))], at: c.dateAdded || null };
  } catch (e) { problems.push(`GHL contact ${id}: ${e.message}`); break; }
}
for (const u of [...new Set(Object.values(ghlCalls).map((x) => x.u).filter(Boolean))].filter((u) => !(u in ghlUsers))) {
  const r = await ghl(`/users/${u}`, "2021-07-28", { allow404: true }).catch(() => null);
  ghlUsers[u] = r ? (r.name || `${r.firstName || ""} ${r.lastName || ""}`.trim() || null) : null;
}
// lookups
const byPhone = {}, byEmail = {}, byRR = {}, byName = {};
for (const [id, c] of Object.entries(ghlContacts)) {
  c.ph.forEach((h) => (byPhone[h] = byPhone[h] || new Set()).add(id));
  c.em.forEach((h) => (byEmail[h] = byEmail[h] || new Set()).add(id));
  c.rr.forEach((r) => (byRR[r] = byRR[r] || new Set()).add(id));
  c.n.forEach((n) => (byName[n] = byName[n] || new Set()).add(id));
}
const callsOf = {};
for (const [mid, x] of Object.entries(ghlCalls)) (callsOf[x.c] = callsOf[x.c] || []).push({ id: mid, ...x });

// ---------- 2. AccuLynx jobs with an appointment set ----------
const jobs = parseCsv(readFileSync(join(DIR, "job_export_raw_latest.csv"), "utf8"))
  .map((r) => ({ rr: (r["Job Number"] || "").trim(), guid: ((r["Job Number Url"] || "").match(/jobs\/([0-9a-f-]{36})/) || [])[1],
    name: r["Primary Contact: Name"], setter: r["Appointment Set By"] || null, rep: r["Primary Salesperson"] || null,
    lead: acxDate(r["Lead Milestone Date"]), set: acxDate(r["Prospect Milestone Date"]), appt: acxDate(r["Initial Appointment Date"]),
    milestone: r["Current Milestone"], source: r["Sub Lead Source"] || r["Parent Lead Source"] || null }))
  .map((j) => ({ ...j, key: j.rr || j.guid }))   // jobs get an RR number only once sold or set up; until then the AccuLynx job id is the key
  .filter((j) => j.guid && j.appt && (j.lead || j.set || j.appt) >= new Date(Date.now() - BACKFILL_DAYS * 864e5));
console.log(`calls: ${jobs.length} jobs with an appointment in the last ${BACKFILL_DAYS} days`);

// AccuLynx contact phones and emails (hashed), once per job; newest jobs first so today's bookings never wait on the backfill
let looked = 0;
for (const j of jobs.sort((a, b) => (b.set || b.appt) - (a.set || a.appt))) {
  if (!acxContacts[j.key] && acxContacts[j.guid]) acxContacts[j.key] = acxContacts[j.guid];
  if (acxContacts[j.key] || looked >= MAX_JOBS) continue;
  looked++;
  try {
    const list = await acx(`/jobs/${j.guid}/contacts?includes=contact`, { allow404: true });
    const ph = new Set(), em = new Set();
    for (const jc of list?.items || []) {
      const cid = jc.contact?.id; if (!cid) continue;
      const c = await acx(`/contacts/${cid}`, { allow404: true });
      for (const p of c?.phoneNumbers || []) {
        const v = p.number ?? (p._link ? (await acx(p._link, { allow404: true }))?.number : null);
        if (digits10(v)) ph.add(hash(digits10(v)));
      }
      for (const e of c?.emailAddresses || []) {
        const v = e.address ?? (e._link ? (await acx(e._link, { allow404: true }))?.address : null);
        if (normEmail(v)) em.add(hash(normEmail(v)));
      }
    }
    acxContacts[j.key] = { ph: [...ph], em: [...em], at: new Date().toISOString() };
  } catch (e) { problems.push(`AccuLynx contacts ${j.key}: ${e.message}`); if (/HTTP 4(01|03)/.test(e.message)) break; }
}

// ---------- 3. match each job to its GHL contact, then save its calls ----------
let transcripts = 0;
const near = (a, b, days) => a && b && Math.abs(new Date(a) - new Date(b)) <= days * 864e5;
for (const j of jobs) {
  const ac = acxContacts[j.key] || acxContacts[j.guid] || { ph: [], em: [] };
  const score = {}, how = {};
  const add = (ids, pts, why) => ids && [...ids].forEach((id) => { score[id] = (score[id] || 0) + pts; (how[id] = how[id] || new Set()).add(why); });
  if (j.rr) add(byRR[j.rr], 100, "RR number");
  ac.ph.forEach((h) => add(byPhone[h], 50, "phone"));
  ac.em.forEach((h) => add(byEmail[h], 40, "email"));
  for (const n of nameKeys(j.name)) add([...(byName[n] || [])].filter((id) => near(ghlContacts[id].at, j.lead || j.set, 60) || (callsOf[id] || []).some((c) => near(c.t, j.set || j.lead, 14))), 25, "name");
  const ranked = Object.entries(score).filter(([id]) => (callsOf[id] || []).length).sort((a, b) => b[1] - a[1]);
  const prev = index[j.key];
  if (!ranked.length) {
    index[j.key] = { rr: j.rr, guid: j.guid, setter: j.setter, set_on: day(j.set), appt: day(j.appt), matched_by: "", ghl_contact: "", calls: 0, booking_call: "", booking_seconds: "", ghl_setter: "",
      tried: [ac.ph.length ? "phone" : "no phone in AccuLynx", ac.em.length ? "email" : "no email in AccuLynx", "name", "RR number"].join("; "), acx_checked: (acxContacts[j.key] || acxContacts[j.guid]) ? "yes" : "not yet" };
    if (JSON.stringify(prev) !== JSON.stringify(index[j.key])) changed = true;
    continue;
  }
  const [cid, pts] = ranked[0];
  const window = (callsOf[cid] || []).filter((c) => (!j.appt || new Date(c.t) <= new Date(j.appt.getTime() + 864e5)) && (!j.lead || new Date(c.t) >= new Date(j.lead.getTime() - 3 * 864e5)))
    .sort((a, b) => String(a.t).localeCompare(String(b.t)));
  const talked = window.filter((c) => (c.s || 0) >= 20);
  // the booking call: the longest call on the day the appointment was set; if none that day, the longest before the appointment
  const onSetDay = talked.filter((c) => j.set && day(c.t) === day(j.set));
  const booking = (onSetDay.length ? onSetDay : talked).slice().sort((a, b) => (b.s || 0) - (a.s || 0))[0] || null;
  const file = join(OUT, "jobs", `${j.key}.json`), pre = join(OUT, "jobs", `${j.guid}.json`);
  const old = existsSync(file) ? JSON.parse(readFileSync(file, "utf8")) : existsSync(pre) ? JSON.parse(readFileSync(pre, "utf8")) : null;
  if (j.rr && existsSync(pre)) { rmSync(pre); changed = true; }   // it has an RR number now
  const have = Object.fromEntries((old?.calls || []).filter((c) => c.transcript).map((c) => [c.id, c.transcript]));
  const calls = [];
  for (const c of window) {
    let tr = have[c.id] || null;
    if (!tr && (c.s || 0) >= 20 && transcripts < MAX_TRANSCRIPTS) {
      const raw = await ghl(`/conversations/locations/${LOCATION}/messages/${c.id}/transcription`, "2021-04-15", { allow404: true }).catch(() => null);
      transcripts++;
      if (Array.isArray(raw) && raw.length) {
        const sides = {}; for (const s of raw) (sides[s.mediaChannel] = sides[s.mediaChannel] || []).push(s.transcript);
        const ours = Object.entries(sides).find(([, t]) => /rapid roofing/i.test(t.join(" ")))?.[0] ?? (c.d === "outbound" ? "2" : "1");
        tr = raw.map((s) => `${String(s.mediaChannel) === String(ours) ? "Setter" : "Customer"}: ${scrub(s.transcript)}`).join("\n");
      }
    }
    calls.push({ id: c.id, at: c.t, direction: c.d, seconds: c.s, status: c.st, user: ghlUsers[c.u] || null, booking_call: c === booking, transcript: tr });
  }
  const rec = { rr: j.rr, acculynx_job: j.guid, customer: j.name, lead_source: j.source, setter_in_acculynx: j.setter, appointment_set_on: day(j.set), appointment: j.appt?.toISOString() || null,
    current_milestone: j.milestone, ghl_contact: cid, matched_by: [...how[cid]].join(" + "), match_points: pts, other_candidates: ranked.length - 1,
    booking_call: booking ? { id: booking.id, at: booking.t, seconds: booking.s, setter: ghlUsers[booking.u] || null } : null, calls };
  if (JSON.stringify(old) !== JSON.stringify(rec)) { writeFileSync(file, JSON.stringify(rec, null, 1) + "\n"); changed = true; }
  index[j.key] = { rr: j.rr, guid: j.guid, setter: j.setter, set_on: day(j.set), appt: day(j.appt), matched_by: rec.matched_by, ghl_contact: cid, calls: calls.length,
    booking_call: booking?.t || "", booking_seconds: booking?.s ?? "", ghl_setter: booking ? ghlUsers[booking.u] || "" : "", tried: "", acx_checked: "yes" };
}

// ---------- 4. save ----------
const q = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
const cols = ["rr", "guid", "setter", "set_on", "appt", "matched_by", "ghl_contact", "calls", "booking_call", "booking_seconds", "ghl_setter", "acx_checked"];
const rows = Object.values(index).sort((a, b) => String(b.set_on || b.appt).localeCompare(String(a.set_on || a.appt)));
writeFileSync(join(OUT, "index.csv"), cols.join(",") + "\n" + rows.map((r) => cols.map((c) => q(r[c])).join(",")).join("\n") + "\n");
const um = rows.filter((r) => !r.matched_by);
writeFileSync(join(OUT, "unmatched.csv"), "rr,guid,setter,set_on,appt,tried,acx_checked\n" + um.map((r) => ["rr", "guid", "setter", "set_on", "appt", "tried", "acx_checked"].map((c) => q(r[c])).join(",")).join("\n") + "\n");
for (const [f, v] of [["_state.json", state], ["_ghl_calls.json", ghlCalls], ["_ghl_contacts.json", ghlContacts], ["_ghl_users.json", ghlUsers], ["_acx_contacts.json", acxContacts], ["_index.json", index]]) saveJson(f, v);
if (newCalls || looked) changed = true;
const matched = rows.length - um.length;
console.log(`calls: ${matched} of ${rows.length} jobs matched (${um.length} unmatched), ${transcripts} transcripts fetched this run, ${looked} AccuLynx jobs looked up`);
out("calls_changed", String(changed));
if (problems.length) { console.error("calls problems:\n" + problems.slice(0, 20).join("\n")); }
