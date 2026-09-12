/** Real login/rendered UI; explicitly synthetic ABDM transport, no clinical DB writes. */
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer";
import { baseUrl, click, field, login, open } from "./acceptance-support.mjs";

const dir = process.env.E2E_EVIDENCE_DIR ?? "../docs/evidence/abdm-pdf-ui";
await mkdir(dir, { recursive: true });
const report = { completed: false, passed: false, baseUrl,
  transport: "Real Keycloak/browser. Synthetic intercepted ABDM responses; no clinical writes or NHA requests.", checks: [] };
const save = () => writeFile(path.join(dir, "result.json"), JSON.stringify(report, null, 2));
await save();

function syntheticPdf() {
  const stream = "BT /F1 22 Tf 30 700 Td (SYNTHETIC ABDM PDF - NOT CLINICAL) Tj ET";
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R /OpenAction 6 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R /Annots [7 0 R] >>",
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    "<< /S /JavaScript /JS (app.alert\\(\\\"PDF_SCRIPT_MUST_NOT_EXECUTE\\\"\\)) >>",
    "<< /Type /Annot /Subtype /Link /Rect [0 0 600 792] /A << /S /URI /URI (https://untrusted.invalid/pdf-link) >> >>",
  ];
  let output = "%PDF-1.4\n"; const offsets = [0];
  objects.forEach((object, i) => { offsets.push(output.length); output += `${i + 1} 0 obj\n${object}\nendobj\n`; });
  const xref = output.length;
  output += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (const offset of offsets.slice(1)) output += `${String(offset).padStart(10, "0")} 00000 n \n`;
  output += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
  return Buffer.from(output).toString("base64");
}

const patient = randomUUID(), record = randomUUID(), now = new Date().toISOString();
const bundle = { resourceType: "Bundle", type: "document", entry: [
  { resource: { resourceType: "Composition", title: "Synthetic external PDF", status: "final" } },
  { resource: { resourceType: "Binary", contentType: "application/pdf", data: syntheticPdf() } },
] };
const workspace = { patient_id: patient, patient_name: "Synthetic PDF Patient", abha_address: "synthetic@sbx",
  identity_verified: true, requester_ready: false, next_offset: null,
  requests: [{ id: randomUUID(), status: "granted", delivery_status: "done", hi_types: ["Prescription"],
    date_range_from: now, date_range_to: now, requested_expiry: now, artefacts: [],
    transfers: [{ id: randomUUID(), status: "received", delivery_status: "done", received_pages: 1, expected_pages: 1,
      records: [{ id: record, hi_type: "Prescription", source_hip_id: "SYNTHETIC-HIP", document_at: now, status: "stored", available: true }] }] }] };
const browser = await puppeteer.launch({ headless: true, acceptInsecureCerts: true,
  defaultViewport: { width: 1440, height: 1100 }, args: ["--no-sandbox"], executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined });
let session, page, revoked = false, recordReads = 0;
const errors = [], external = [], writes = [], dialogs = [];
function respond(request, data, status = 200) {
  return request.respond({ status, contentType: "application/json", body: JSON.stringify({
    success: status < 400, data: status < 400 ? data : null,
    error: status < 400 ? null : { code: "record_unavailable", message: "External record unavailable" }, meta: {},
  }) });
}
async function evidence(name) {
  const screenshot = `check-${report.checks.length + 1}.png`;
  await page.screenshot({ path: path.join(dir, screenshot), fullPage: true });
  report.checks.push({ name, passed: true, screenshot }); console.log(`PASS ${name}`); await save();
}
try {
  session = await login(browser, "dev.doctor"); page = session.page;
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("dialog", async (dialog) => { dialogs.push(dialog.type()); await dialog.dismiss(); });
  await page.setRequestInterception(true);
  page.on("request", (request) => {
    const url = new URL(request.url()), route = url.pathname;
    if (url.hostname === "untrusted.invalid") { external.push(route); return void request.abort(); }
    if (route === "/api/v1/patients/search") return void respond(request, { items: [{ id: patient, full_name: "Synthetic PDF Patient", uhid: "SYNTH-PDF", sex: "other", age_years: 30 }] });
    if (!route.startsWith("/api/v1/abdm/")) return void request.continue();
    if (!/^Bearer /.test(request.headers().authorization ?? "")) { errors.push("Missing bearer on ABDM UI request"); return void request.abort(); }
    if (request.method() !== "GET") { writes.push(route); return void request.abort(); }
    if (route.endsWith("/workspace")) return void respond(request, workspace);
    if (route.endsWith("/care-contexts") || route.endsWith("/links")) return void respond(request, []);
    if (route === `/api/v1/abdm/hiu/records/${record}`) { recordReads++; return void respond(request, bundle, revoked ? 404 : 200); }
    errors.push(`Unexpected ABDM path ${route}`); return void request.abort();
  });
  await open(page, "/doctor/abdm");
  await field(page, "Find patient by name", "Synthetic PDF Patient");
  await field(page, "Date of birth", "1996-01-01");
  await click(page, "Search patients");
  await click(page, "Synthetic PDF Patient · SYNTH-PDF · other · 30");
  await click(page, "View record");
  await click(page, "Preview PDF attachment 1");
  await page.waitForFunction(() => {
    const c = document.querySelector("canvas[aria-label]");
    if (!c || c.width < 100) return false;
    const pixels = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
    let ink = 0;
    for (let i = 0; i < pixels.length; i += 4) if (pixels[i + 3] > 0 && pixels[i] < 180 && pixels[i + 1] < 180 && pixels[i + 2] < 180) ink++;
    return ink > 100;
  }, { timeout: 45000 });
  assert.deepEqual(errors, []); assert.deepEqual(dialogs, []);
  assert.equal(await page.$$('[aria-label="External clinical record"] iframe, [aria-label="External clinical record"] object, [aria-label="External clinical record"] embed').then((nodes) => nodes.length), 0);
  await page.click("canvas[aria-label]");
  assert.deepEqual(external, []); assert.deepEqual(writes, []);
  await evidence("Real browser renders synthetic PDF to canvas without executing its script or opening links");
  revoked = true; const before = recordReads;
  await page.waitForFunction(() => !document.querySelector("canvas[aria-label]"), { timeout: 20000 });
  await page.waitForFunction(() => document.querySelector('[aria-label="External clinical record"] [role="alert"]'), { timeout: 20000 });
  assert.ok(recordReads > before, "Must actually recheck access");
  await evidence("Failed consent refresh removes PDF canvas and displays refusal");
  assert.deepEqual(errors, []); assert.deepEqual(external, []); assert.deepEqual(writes, []); assert.deepEqual(dialogs, []);
  report.completed = true; report.passed = true;
} catch (error) {
  report.error = String(error.message);
  if (page) await page.screenshot({ path: path.join(dir, "failure.png"), fullPage: true }).catch(() => {});
  process.exitCode = 1;
} finally { await save(); await session?.context.close(); await browser.close(); }
console.log(JSON.stringify(report, null, 2));
