/** Real Keycloak + real rendered app, explicitly simulated patient/OTP transport.
 * Fault-injection evidence, NOT an ABDM round trip. No OTP reaches the server.
 */
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer";
import { baseUrl, click, field, login, open } from "./acceptance-support.mjs";

const evidenceDir = process.env.E2E_EVIDENCE_DIR ?? "../docs/evidence/patient-switch";
await mkdir(evidenceDir, { recursive: true });
const report = { runId: process.env.E2E_RUN_ID, baseUrl, completed: false, passed: false, transport: "Real Keycloak; simulated patient reads and OTP responses only", checks: [] };
const save = () => writeFile(path.join(evidenceDir, "patient-switch.json"), JSON.stringify(report, null, 2));
await save();
const patients = ["Alpha", "Beta", "Gamma"].map((name, i) => ({
  id: randomUUID(), full_name: `Synthetic Switch ${name}`, uhid: `SYNTHETIC-${i}`, sex: "female", age_years: 36,
  mobile_masked: null, matched_on: "name_dob", match_score: 1, abha_number: null,
}));
const tokens = patients.map((p, i) => ({ ...p, id: randomUUID(), patient_id: p.id, queue_id: randomUUID(), visit_id: randomUUID(), sequence: i + 1, token_display: `TEST-${i}`, status: "waiting", priority: "normal", created_at: new Date().toISOString() }));
const browser = await puppeteer.launch({ headless: true, acceptInsecureCerts: true, defaultViewport: { width: 1440, height: 1000 }, executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined, args: ["--no-sandbox"] });

async function record(page, name) {
  const screenshot = `switch__${report.checks.length + 1}.png`;
  await page.screenshot({ path: path.join(evidenceDir, screenshot), fullPage: true });
  report.checks.push({ name, passed: true, screenshot });
  console.log(`PASS ${name}`);
  await save();
}
async function selectPatient(page, patient, reception = false) {
  await page.waitForFunction((name) => [...document.querySelectorAll("tbody tr")].some((r) => r.textContent.includes(name)), {}, patient.full_name);
  await page.evaluate((name, choose) => {
    const row = [...document.querySelectorAll("tbody tr")].find((r) => r.textContent.includes(name));
    (choose ? row.querySelector("button") : row).click();
  }, patient.full_name, reception);
}
const settleRender = (page) => page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
async function summary(page) {
  return page.evaluate(() => {
    const heading = [...document.querySelectorAll("#main-content p")].find((n) => n.textContent === "Known Allergies");
    return heading?.parentElement?.parentElement?.textContent ?? "";
  });
}
async function waitSummary(page, wanted) {
  await page.waitForFunction((value) => {
    const h = [...document.querySelectorAll("#main-content p")].find((n) => n.textContent === "Known Allergies");
    return h?.parentElement?.parentElement?.textContent.includes(value);
  }, { timeout: 30_000 }, wanted);
}
function json(request, data, status = 200) {
  return request.respond({ status, contentType: "application/json", body: JSON.stringify(status === 200 ? { success: true, data, error: null, meta: {} } : { success: false, data: null, error: { code: status, message: "Synthetic unavailable response" }, meta: {} }) });
}

let session;
try {
  session = await login(browser, "dev.doctor");
  const { page } = session;
  const pending = [];
  let hold = null;
  let fail = null;
  let holdAccess = null;
  let deniedAccess = null;
  const accessPending = [];
  let observed = 0;
  await page.setRequestInterception(true);
  page.on("request", (request) => {
    const route = new URL(request.url()).pathname;
    const patient = patients.find((p) => route.endsWith(`/${p.id}`) || route.endsWith(`/${p.id}/history`));
    if (route === "/api/v1/queue/worklist") return void json(request, { items: tokens });
    if (!patient) return void request.continue();
    assert.match(request.headers().authorization ?? "", /^Bearer /);
    if (route.startsWith("/api/v1/break-glass/access/")) {
      const result = { patient_id: patient.id, allowed: patient.id !== deniedAccess, blocked_reason: patient.id === deniedAccess ? "consent_absent" : null, grant: null };
      if (patient.id === holdAccess) accessPending.push(() => json(request, result));
      else void json(request, result);
      return;
    }
    const kind = route.endsWith("/history") ? "history" : route.includes("/allergies/") ? "allergies" : "patient";
    const data = kind === "patient" ? patient : kind === "allergies" ? [{ id: randomUUID(), patient_id: patient.id, substance_text: `ALLERGY-${patient.full_name}`, severity: "mild", reaction: "synthetic only" }] : {
      visits: [{ visit_id: patient.id, visit_number: "SYNTHETIC", started_at: "2026-01-01" }],
      encounters: [{ encounter_id: patient.id, visit_id: patient.id }],
      diagnoses: [{ encounter_id: patient.id, diagnosis_text: `HISTORY-${patient.full_name}`, is_primary: true }],
    };
    observed += 1;
    if (hold === patient.id) pending.push({ kind, release: () => json(request, data) });
    else void json(request, data, fail === patient.id && kind !== "patient" ? 503 : 200);
  });
  await open(page, "/doctor/dashboard");
  await waitSummary(page, `ALLERGY-${patients[0].full_name}`);
  hold = patients[1].id;
  await selectPatient(page, patients[1]);
  await waitSummary(page, "Loading allergies");
  assert.ok(!(await summary(page)).includes(patients[0].full_name), "Old patient must disappear while next patient loads");
  await record(page, "Doctor switch clears previous demographics, allergies and history before new reads finish");
  await selectPatient(page, patients[2]);
  await waitSummary(page, `HISTORY-${patients[2].full_name}`);
  // StrictMode and the consent gate can remount the summary. Assert the
  // required read families, not a production-only assumption of one request.
  assert.deepEqual([...new Set(pending.map((entry) => entry.kind))].sort(), ["allergies", "history", "patient"]);
  await Promise.all(pending.splice(0).map(({ release }) => release()));
  await settleRender(page);
  assert.ok(!(await summary(page)).includes(patients[1].full_name), "Late reads must not replace current patient");
  await record(page, "Doctor ignores all three late responses after another patient switch");
  hold = null;
  fail = patients[1].id;
  await selectPatient(page, patients[1]);
  await waitSummary(page, "Clinical history unavailable.");
  assert.match(await summary(page), /Allergy status unavailable/);
  assert.doesNotMatch(await summary(page), /None recorded|First visit/);
  await record(page, "Doctor failed allergy/history reads are unavailable, never a reassuring empty state");
  fail = null;
  await click(page, "Retry patient summary");
  await waitSummary(page, `ALLERGY-${patients[1].full_name}`);
  await waitSummary(page, `HISTORY-${patients[1].full_name}`);
  assert.ok(observed >= 12, "Retries must really reread patient data");
  await record(page, "Doctor retry restores independently fetched clinical data");
  holdAccess = patients[0].id;
  deniedAccess = patients[2].id;
  const checkingAccess = page.waitForRequest((r) => new URL(r.url()).pathname === `/api/v1/break-glass/access/${patients[0].id}`);
  await selectPatient(page, patients[0]);
  await checkingAccess;
  await selectPatient(page, patients[2]);
  await page.waitForFunction(() => document.querySelector("#main-content")?.textContent.includes("Record locked"));
  assert.ok(accessPending.length, "Previous patient's access check must be in flight");
  const readsBefore = observed;
  await Promise.all(accessPending.splice(0).map((release) => release()));
  await settleRender(page);
  assert.match(await page.$eval("#main-content", (n) => n.textContent), /Record locked/, "Late permission for a different patient cannot unlock this record");
  assert.equal(observed, readsBefore, "Denied patient's chart must not be fetched using an obsolete access decision");
  await record(page, "Late access approval for another patient cannot unlock a denied record");
  await session.context.close();
  session = await login(browser, "dev.receptionist");
  const reception = session.page;
  let pendingOtp = null;
  let pendingVerify = null;
  let otpRequests = 0;
  await reception.setRequestInterception(true);
  reception.on("request", (request) => {
    const route = new URL(request.url()).pathname;
    if (route === "/api/v1/patients/search") return void json(request, { items: patients, page: 1, page_size: 20, total: 3 });
    // Fail closed for EVERY ABHA route, including routes this test doesn't use.
    if (route.startsWith("/api/v1/abdm/abha/")) {
      assert.match(request.headers().authorization ?? "", /^Bearer /);
      if (route.endsWith("/request-otp")) { otpRequests += 1; pendingOtp = request; }
      else if (route.endsWith("/verify-otp")) pendingVerify = request;
      else void request.abort();
      return;
    }
    void request.continue();
  });
  await open(reception, "/receptionist/registration");
  await field(reception, "Name", "Synthetic Switch");
  await field(reception, "Date of birth", "1990-01-01");
  await click(reception, "Search");
  await selectPatient(reception, patients[0], true);
  // There is also a search ABHA field. Scope the identifier to the panel.
  const identifier = async () => reception.evaluate(() => [...document.querySelectorAll("label")].filter((l) => l.querySelector("span")?.textContent === "ABHA number").at(-1)?.querySelector("input")?.value);
  const enterIdentifier = async () => reception.evaluate(() => {
    const input = [...document.querySelectorAll("label")].filter((l) => l.querySelector("span")?.textContent === "ABHA number").at(-1).querySelector("input");
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, "91000000000001");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await enterIdentifier();
  const firstOtp = reception.waitForRequest((r) => new URL(r.url()).pathname.endsWith("/login/request-otp"));
  await click(reception, "Send OTP");
  await firstOtp;
  assert.ok(pendingOtp, "A delayed OTP request must exist");
  assert.equal(JSON.parse(pendingOtp.postData()).patient_id, patients[0].id);
  await selectPatient(reception, patients[1], true);
  await settleRender(reception);
  assert.equal(await identifier(), "");
  await json(pendingOtp, { session_id: randomUUID(), masked_mobile: "SYNTHETIC-ALPHA-DESTINATION" });
  await settleRender(reception);
  assert.doesNotMatch(await reception.$eval("#main-content", (n) => n.textContent), /SYNTHETIC-ALPHA-DESTINATION/);
  assert.equal(await reception.$$eval("button", (buttons) => buttons.some((b) => b.textContent.trim() === "Verify and link")), false);
  await record(reception, "Reception discards prior patient identifier and ignores late OTP destination/session");
  pendingOtp = null;
  await enterIdentifier();
  const sent = reception.waitForRequest((r) => new URL(r.url()).pathname.endsWith("/login/request-otp"));
  await click(reception, "Send OTP");
  await sent;
  await json(pendingOtp, { session_id: randomUUID(), masked_mobile: "SYNTHETIC-BETA-DESTINATION" });
  await reception.waitForFunction(() => document.body.textContent.includes("SYNTHETIC-BETA-DESTINATION"));
  await field(reception, "OTP", "123456");
  const verifying = reception.waitForRequest((r) => new URL(r.url()).pathname.endsWith("/login/verify-otp"));
  await click(reception, "Verify and link");
  await verifying;
  await selectPatient(reception, patients[2], true);
  await json(pendingVerify, { linked: true, linked_patient_id: patients[1].id, abha_number: "91000000000001", abha_address: "synthetic-beta@example.invalid" });
  await settleRender(reception);
  assert.doesNotMatch(await reception.$eval("#main-content", (n) => n.textContent), /ABHA verified and linked|SYNTHETIC-BETA-DESTINATION|synthetic-beta@example/);
  assert.equal(await identifier(), "");
  assert.equal(otpRequests, 2);
  await record(reception, "Reception ignores late verification success for the previous patient");
  report.completed = true;
  report.passed = true;
} catch (error) {
  report.failure = error.message;
  if (session) await session.page.screenshot({ path: path.join(evidenceDir, "switch-failure.png"), fullPage: true }).catch(() => {});
  throw error;
} finally {
  await browser.close();
  await save();
}
