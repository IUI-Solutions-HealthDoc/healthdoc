/** Rendered local app + real Keycloak, explicitly SIMULATED clinical transport.
 * No patient/order/result is created in the application DB. This is UI/fault
 * acceptance, not proof of a persisted referral journey or ABDM exchange.
 */
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer";
import { baseUrl, click, field, login, open } from "./acceptance-support.mjs";

const dir = process.env.E2E_EVIDENCE_DIR ?? "../docs/evidence/external-results-ui";
await mkdir(dir, { recursive: true });
const report = { runId: process.env.E2E_RUN_ID, baseUrl, completed: false, passed: false,
  transport: "Real Keycloak and rendered UI; queue, encounter, order and result transport simulated. No clinical DB writes.", checks: [] };
const save = () => writeFile(path.join(dir, "external-results-ui.json"), JSON.stringify(report, null, 2));
await save();
const browser = await puppeteer.launch({ headless: true, acceptInsecureCerts: true,
  defaultViewport: { width: 1440, height: 1100 }, args: ["--no-sandbox"], executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined });
const patient = randomUUID(), visit = randomUUID(), encounter = randomUUID(), doctor = randomUUID(), orderId = randomUUID();
const order = { id: orderId, order_number: "SYNTH-EXT-001", patient_id: patient, encounter_id: encounter,
  order_type: "lab", priority: "routine", status: "placed", fulfilment_mode: "external_referral", completed_at: null,
  ordered_at: new Date().toISOString() };
let session, page, failWrite = true, failRead = false;
const rows = [], posts = [], errors = [];
async function evidence(name) {
  const screenshot = `external-result-${report.checks.length + 1}.png`;
  await page.screenshot({ path: path.join(dir, screenshot), fullPage: true });
  report.checks.push({ name, passed: true, screenshot }); console.log(`PASS ${name}`); await save();
}
async function waitText(text) {
  await page.waitForFunction((wanted) => document.querySelector("#main-content")?.textContent.includes(wanted), { timeout: 30000 }, text);
}
function respond(request, data, status = 200) {
  return request.respond({ status, contentType: "application/json", body: JSON.stringify({
    success: status < 400, data: status < 400 ? data : null,
    error: status < 400 ? null : { code: status, message: "Synthetic transport failure" }, meta: {},
  }) });
}
try {
  session = await login(browser, "dev.doctor"); page = session.page;
  page.on("pageerror", (error) => {
    const failure = { message: error.message, stack: error.stack,
      afterCheck: report.checks.at(-1)?.name ?? "initial load" };
    errors.push(failure);
    console.error("Browser error", failure);
  });
  await page.setRequestInterception(true);
  page.on("request", (request) => {
    const route = new URL(request.url()).pathname;
    const clinical = route === "/api/v1/queue/worklist" || route === `/api/v1/encounters/by-visit/${visit}` ||
      route === "/api/v1/orders" || route === "/api/v1/procedures" || route === `/api/v1/orders/${orderId}/external-results`;
    if (!clinical) return void request.continue();
    if (!/^Bearer /.test(request.headers().authorization ?? "")) {
      errors.push("Clinical request missing bearer token"); return void request.abort();
    }
    if (route === "/api/v1/queue/worklist") return void respond(request, { items: [{ id: randomUUID(), patient_id: patient,
      full_name: "Synthetic External Result Patient", uhid: "SYNTH-EXT-PATIENT", visit_id: visit,
      provider_user_id: doctor, provider_name: "Synthetic Doctor", department: "Synthetic clinic", status: "in_service" }] });
    if (route === `/api/v1/encounters/by-visit/${visit}`) return void respond(request, {
      id: encounter, visit_id: visit, provider_user_id: doctor, note_status: "signed", row_version: 1,
      started_at: new Date().toISOString(), ended_at: new Date().toISOString(),
    });
    if (route === "/api/v1/orders") return void respond(request, { items: [order] });
    if (route === "/api/v1/procedures") return void respond(request, { items: [] });
    if (request.method() === "GET") return void respond(request, { items: rows }, failRead ? 503 : 200);
    const body = JSON.parse(request.postData()), key = request.headers()["idempotency-key"];
    if (!key) { errors.push("Result write missing action key"); return void request.abort(); }
    posts.push({ body, key }); // Memory only; never evidence.
    if (rows.length === 0) {
      rows.push({ ...body, id: randomUUID(), order_id: orderId, recorded_by: doctor,
        recorded_at: new Date().toISOString(), result_file_id: null });
      order.status = "completed"; order.completed_at = new Date().toISOString();
    }
    if (failWrite) { failWrite = false; return void respond(request, null, 503); }
    return void respond(request, rows[0], 201);
  });
  await open(page, "/doctor/orders"); await waitText("SYNTH-EXT-001");
  assert.equal(await page.evaluate(() => [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "+ Add order")?.disabled), true);
  await click(page, "Referred externally"); await click(page, "Outside results"); await waitText("No outside results recorded.");
  await evidence("Completed consultation locks new orders but opens outside-result history for its referral");
  await click(page, "Record outside result"); await waitText("Enter the outside result summary."); assert.equal(posts.length, 0);
  await evidence("Empty summary and absent patient confirmation block the browser write");
  await field(page, "Outside provider (optional)", "Synthetic Outside Provider");
  const initialSummary = "Synthetic external result summary — not a clinical report.";
  const continuation = "\n" + "Synthetic continuation for keyboard regression. ".repeat(20).trimEnd();
  const summary = initialSummary + continuation;
  const summarySelector = 'textarea:not([aria-hidden="true"])';
  await page.$eval(summarySelector, (input) => {
    const setValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
    // A burst of input events makes pending lower-priority form updates visible
    // without depending on machine speed or adding sleeps to the test.
    for (let length = 1; length <= 128; length++) {
      setValue.call(input, "x".repeat(length));
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }
    setValue.call(input, "");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  assert.deepEqual(errors, [], "A burst of input events must not produce a runtime error");
  // Locator.fill switches long strings to a single synthetic input event.
  // Exercise actual, zero-delay keystrokes: repeated controlled MUI updates
  // previously raised Maximum update depth exceeded during summary entry.
  // Retain the original short locator interaction as well as the long typing.
  await page.locator(summarySelector).fill(initialSummary);
  await page.type(summarySelector, continuation);
  assert.deepEqual(errors, [], "Typing must not produce a runtime error");
  assert.equal(await page.$eval(summarySelector, (node) => node.value), summary, "Every typed character must survive rendering");
  await evidence("Long multiline keyboard entry preserves every character without a runtime error");
  await page.click('input[type="checkbox"]');
  await click(page, "Record outside result"); await waitText("The original entry is locked for a safe retry.");
  assert.equal(posts.length, 1); assert.equal(await page.$eval("textarea", (node) => node.disabled), true);
  assert.equal(posts[0].body.summary, summary, "The submitted summary must match the displayed draft");
  await evidence("Ambiguous submission locks the original result for an exact retry");
  await click(page, "Retry same result"); await waitText("Result recorded for"); await waitText("Synthetic external result summary");
  assert.equal(posts.length, 2); assert.deepEqual(posts[0], posts[1]); assert.equal(rows.length, 1);
  await waitText("completed"); await evidence("Retry preserves body/key and receipt survives the order refresh");
  failRead = true; await click(page, "Refresh result history"); await waitText("temporarily unavailable");
  assert.ok((await page.$eval("#main-content", (node) => node.textContent)).includes("Result recorded for"));
  await evidence("Failed history refresh retains the confirmed write receipt");
  failRead = false; await click(page, "Refresh result history"); await waitText("Synthetic external result summary");
  await click(page, "Record another result / correction");
  await page.waitForSelector(summarySelector);
  assert.equal(await page.$eval(summarySelector, (node) => node.value), "");
  for (const fieldId of [`${orderId}-provider`, `${orderId}-observed`]) {
    assert.equal(await page.$eval(`[id="${fieldId}"]`, (node) => node.value), "");
  }
  assert.equal(await page.$eval('input[type="checkbox"]', (node) => node.checked), false);
  assert.equal(posts.length, 2);
  await evidence("A deliberate correction mounts an empty draft without resubmitting the saved entry");
  await open(page, "/doctor/orders"); await click(page, "Outside results"); await waitText("Synthetic external result summary");
  assert.equal(posts.length, 2); await evidence("Reload reads existing history without submitting another result");
  order.status = "cancelled";
  await open(page, "/doctor/orders"); await click(page, "Outside results"); await waitText("History is read-only.");
  assert.equal(await page.$("textarea"), null); await evidence("Cancelled referral retains history but has no result-entry form");
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
