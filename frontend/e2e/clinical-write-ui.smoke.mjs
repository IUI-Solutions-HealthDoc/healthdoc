/** Real Keycloak and rendered forms/blood UI; explicitly SIMULATED clinical
 * transport. No clinical records or facility settings are written to the DB.
 * PostgreSQL receipt/rollback/contention coverage lives in backend tests.
 */
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer";
import { baseUrl, click, login, open } from "./acceptance-support.mjs";

const dir = process.env.E2E_EVIDENCE_DIR ?? "../docs/evidence/clinical-write-ui";
await mkdir(dir, { recursive: true });
const report = { runId: process.env.E2E_RUN_ID, baseUrl, completed: false, passed: false,
  transport: "Real Keycloak/rendered UI; clinical and capability responses intercepted. No clinical DB writes.", checks: [] };
const save = () => writeFile(path.join(dir, "clinical-write-ui.json"), JSON.stringify(report, null, 2));
await save();
const browser = await puppeteer.launch({ headless: true, acceptInsecureCerts: true,
  defaultViewport: { width: 1440, height: 1100 }, args: ["--no-sandbox"],
  executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined });
const patient = { id: randomUUID(), full_name: "Synthetic Retry Patient", uhid: "SYNTH-RETRY-001" };
const definition = { id: randomUUID(), code: "SYNTH_RETRY", title: "Synthetic retry form", version: 1,
  status: "published", fields_schema: [{ id: "answer", label: "Synthetic answer", type: "text",
    required: true, placeholder: "Synthetic retry answer" }] };
const unit = { id: randomUUID(), donor_id: randomUUID(), bag_number: "SYNTH-BAG-001", blood_group: "O+",
  volume_ml: 350, expiry_date: "2099-01-01", screening_status: "passed", status: "available" };
let session, page, submission, crossmatch, issued;
const posts = { form: [], crossmatch: [], issue: [] }, errors = [];
const uncertainText = "Save outcome is not confirmed.";
const waitText = (text) => page.waitForFunction((value) => document.querySelector("#main-content")?.textContent.includes(value),
  { timeout: 30000 }, text);
async function evidence(name) {
  const screenshot = `clinical-write-${report.checks.length + 1}.png`;
  await page.screenshot({ path: path.join(dir, screenshot), fullPage: true });
  report.checks.push({ name, passed: true, screenshot }); console.log(`PASS ${name}`); await save();
}
function respond(request, data, status = 200) {
  return request.respond({ status, contentType: "application/json", body: JSON.stringify({
    success: status < 400, data: status < 400 ? data : null,
    error: status < 400 ? null : { code: status, message: "Synthetic lost write response" }, meta: {},
  }) });
}
try {
  session = await login(browser, "dev.admin"); page = session.page;
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setRequestInterception(true);
  page.on("request", (request) => {
    const route = new URL(request.url()).pathname;
    const clinical = ["/api/v1/facility/capabilities", "/api/v1/patients/search", "/api/v1/forms/definitions",
      "/api/v1/order-sets", `/api/v1/forms/patients/${patient.id}`, "/api/v1/forms/submissions",
      "/api/v1/blood-bank/units", "/api/v1/blood-bank/donors", "/api/v1/blood-bank/crossmatch", "/api/v1/blood-bank/issue"].includes(route);
    if (!clinical) return void request.continue();
    if (!/^Bearer /.test(request.headers().authorization ?? "")) {
      errors.push("Intercepted clinical request lacked bearer authentication"); return void request.abort();
    }
    if (route === "/api/v1/facility/capabilities") return void respond(request, { modules: { blood_bank: true } });
    if (route === "/api/v1/patients/search") return void respond(request, { items: [patient] });
    if (route === "/api/v1/forms/definitions") return void respond(request, [definition]);
    if (route === "/api/v1/order-sets") return void respond(request, []);
    if (route === `/api/v1/forms/patients/${patient.id}`) return void respond(request, submission ? [submission] : []);
    if (route === "/api/v1/blood-bank/units") return void respond(request, [unit]);
    if (route === "/api/v1/blood-bank/donors") return void respond(request, []);
    const body = JSON.parse(request.postData()), key = request.headers()["idempotency-key"];
    if (!key) { errors.push("Clinical write lacked action key"); return void request.abort(); }
    // Bodies and credentials stay in memory and never enter the evidence report.
    if (route === "/api/v1/forms/submissions") {
      posts.form.push({ body, key });
      submission ??= { ...body, id: randomUUID(), form_version: 1, submitted_by: randomUUID(), submitted_at: new Date().toISOString() };
      return void respond(request, submission, posts.form.length === 1 ? 503 : 201);
    }
    if (route === "/api/v1/blood-bank/crossmatch") {
      posts.crossmatch.push({ body, key });
      crossmatch ??= { ...body, id: randomUUID(), crossmatched_at: new Date().toISOString(), issued_at: null };
      return void respond(request, crossmatch, 201);
    }
    posts.issue.push({ body, key });
    issued ??= { ...crossmatch, issued_at: new Date().toISOString() };
    unit.status = "issued";
    return void respond(request, issued, posts.issue.length === 1 ? 503 : 201);
  });
  await open(page, "/forms");
  await page.locator('input[placeholder^="Search patient by"]').fill(patient.uhid);
  await click(page, "Find");
  await page.locator('input[placeholder="Synthetic retry answer"]').fill("Synthetic immutable answer");
  await click(page, "Submit Clinical Form"); await waitText(uncertainText);
  assert.equal(posts.form.length, 1);
  assert.equal(await page.$eval('input[placeholder="Synthetic retry answer"]', (node) => node.matches(":disabled")), true);
  await evidence("Ambiguous form save locks the original draft and exposes an explicit retry");
  await click(page, "Retry unchanged save"); await waitText("Clinical form submitted and recorded successfully!");
  assert.equal(posts.form.length, 2); assert.deepEqual(posts.form[0], posts.form[1]);
  assert.equal(posts.form[0].body.patient_id, patient.id);
  await evidence("Rendered form retry sends the identical body/key and confirms the bound patient receipt");
  await open(page, "/blood-bank"); await waitText(unit.bag_number); await click(page, "Crossmatch");
  await page.locator('input[placeholder^="Enter exact Patient"]').fill(patient.uhid);
  await page.click('button[aria-label="Search patient"]'); await waitText(patient.full_name);
  await page.$eval('input[type="radio"][value="compatible"]', (node) => node.click());
  await page.click('input[type="checkbox"]');
  await page.locator('input[placeholder^="e.g. ICU Bed"]').fill("Synthetic test ward");
  await click(page, "Crossmatch & Issue"); await waitText(uncertainText);
  await waitText("Crossmatch recorded.");
  assert.equal(posts.crossmatch.length, 1); assert.equal(posts.issue.length, 1);
  assert.equal(await page.$eval('button[aria-label="Close crossmatch"]', (node) => node.disabled), true);
  assert.equal(await page.$eval('input[placeholder^="e.g. ICU Bed"]', (node) => node.matches(":disabled")), true);
  await evidence("Confirmed crossmatch survives an ambiguous issue; recipient/destination and close stay locked");
  await click(page, "Retry unchanged save"); await waitText("Blood Unit Issued Successfully");
  assert.equal(posts.crossmatch.length, 1, "Retry must not create a second crossmatch");
  assert.equal(posts.issue.length, 2); assert.deepEqual(posts.issue[0], posts.issue[1]);
  assert.equal(posts.issue[0].body.crossmatch_id, crossmatch.id);
  await evidence("Retry issues the existing crossmatch with its original body/key and displays the confirmed receipt");
  assert.deepEqual(errors, []);
  report.completed = true; report.passed = true;
} catch (error) {
  report.failure = error.message;
  if (page) await page.screenshot({ path: path.join(dir, "failure.png"), fullPage: true }).catch(() => {});
  throw error;
} finally {
  report.browserErrors = errors;
  await save(); await session?.context.close(); await browser.close();
}
