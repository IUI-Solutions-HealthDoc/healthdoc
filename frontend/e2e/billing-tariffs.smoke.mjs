/** Local real-Keycloak acceptance. Clinical fixtures via real APIs; billing via UI.
 * Unique synthetic modality codes avoid changing prices for any existing work.
 * No patient has an ABHA, and no ABDM worker or OTP is started here.
 */
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer";
import { baseUrl, click, field, login, open } from "./acceptance-support.mjs";

assert.equal(process.env.E2E_ALLOW_MUTATIONS, "1", "Opt in to synthetic local records");
const evidenceDir = process.env.E2E_EVIDENCE_DIR ?? "../docs/evidence/billing-tariffs";
await mkdir(evidenceDir, { recursive: true });
const report = { runId: process.env.E2E_RUN_ID, baseUrl, completed: false, passed: false, checks: [], fixtures: {} };
const save = () => writeFile(path.join(evidenceDir, "billing-tariffs.json"), JSON.stringify(report, null, 2));
await save();
const browser = await puppeteer.launch({ headless: true, acceptInsecureCerts: true, defaultViewport: { width: 1440, height: 1000 }, executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined, args: ["--no-sandbox"] });
const sessions = [];
async function role(username, pathname) {
  console.log(`RUN tariff: ${username}`);
  const session = await login(browser, username);
  sessions.push(session);
  await open(session.page, pathname);
  return session;
}
async function record(page, name) {
  const screenshot = `tariff__${report.checks.length + 1}.png`;
  await page.screenshot({ path: path.join(evidenceDir, screenshot), fullPage: true });
  report.checks.push({ name, passed: true, screenshot });
  console.log(`PASS ${name}`);
  await save();
}
async function uiResponse(page, method, pathname, action, status = 200) {
  const waiting = page.waitForResponse((r) => r.request().method() === method && new URL(r.url()).pathname === `/api/v1${pathname}`, { timeout: 30_000 });
  await action();
  const response = await waiting;
  assert.equal(response.status(), status, pathname);
  assert.match(response.request().headers().authorization ?? "", /^Bearer /);
  const body = await response.json();
  return body.data ?? body;
}
const money = (value) => {
  // SUM over no refund rows serializes Decimal(0) as "0", not "0.00".
  // Both are exact decimal strings; never round-trip through a JS float.
  assert.match(value, /^\d+(?:\.\d{1,2})?$/);
  const [whole, fractional = ""] = value.split(".");
  return BigInt(whole) * 100n + BigInt(fractional.padEnd(2, "0"));
};
let page;
try {
  const admin = await role("dev.admin", "/admin");
  const staff = await admin.api("GET", "/users?search=dev.doctor");
  const doctorId = staff.items.find((u) => u.username === "dev.doctor")?.id;
  assert.ok(doctorId);
  const prefix = `e2e-${randomUUID().slice(0, 12)}`;
  const name = `Tariff Test ${randomUUID().replace(/[0-9-]/g, "a")}`;
  const tariff = await admin.api("POST", "/billing/charge-master", { charge_code: prefix, charge_category: "radiology", description: "Synthetic acceptance tariff only", unit_price: "413.27", effective_from: "2020-01-01" }, 201);
  report.fixtures.tariffId = tariff.id;
  const reception = await role("dev.receptionist", "/receptionist/registration");
  const patient = await reception.api("POST", "/patients", { full_name: name, sex: "female", dob: "1990-01-01" }, 201);
  const visit = await reception.api("POST", "/visits", { patient_id: patient.id, visit_type: "day_care", visit_date: new Date().toISOString() }, 201);
  report.fixtures.patientId = patient.id;
  report.fixtures.visitId = visit.id;
  const doctor = await role("dev.doctor", "/doctor/dashboard");
  const encounter = await doctor.api("POST", "/encounters", { visit_id: visit.id, provider_user_id: doctorId, chief_complaint: "Synthetic tariff acceptance. No clinical content." }, 201);
  const items = [];
  for (const modality of [prefix, `${prefix}-missing`]) {
    const order = await doctor.api("POST", "/orders", { encounter_id: encounter.id, patient_id: patient.id, order_type: "radiology" }, 201);
    items.push(await doctor.api("POST", `/radiology/order-items?order_id=${order.id}`, { modality, scan_type: "Synthetic acceptance only" }, 201));
  }
  const tech = await role("dev.radiology", "/radiology");
  for (const item of items) {
    await tech.api("PUT", `/radiology/order-items/${item.id}/schedule`, { scheduled_at: new Date(Date.now() + 3_600_000).toISOString(), machine_id: "SYNTHETIC-TEST" });
    await tech.api("PUT", `/radiology/order-items/${item.id}/scan-complete`, {});
    await doctor.api("POST", `/radiology/order-items/${item.id}/reports`, { findings: "Synthetic acceptance. Not a clinical report.", impression: "Synthetic only." }, 201);
    const final = await doctor.api("PUT", `/radiology/order-items/${item.id}/reports/sign-off`, {});
    assert.equal(final.status, "final");
  }
  const billing = await role("dev.billing", "/billing");
  page = billing.page;
  const preview = await billing.api("GET", `/billing/visits/${visit.id}/invoice/preview`);
  const priced = preview.new_charge_lines.find((line) => line.reference_id === items[0].id);
  const unpriced = preview.new_charge_lines.find((line) => line.reference_id === items[1].id);
  assert.equal(priced.unit_price, "413.27");
  assert.equal(priced.charge_master_id, tariff.id);
  assert.equal(unpriced.priced, false);
  assert.equal(preview.unpriced_count, 1);
  report.fixtures.invoiceId = preview.invoice_id;
  await field(page, "Search invoices", name);
  await page.waitForFunction((wanted) => [...document.querySelectorAll("button")].some((b) => b.textContent.includes(wanted)), {}, name);
  await page.evaluate((wanted) => [...document.querySelectorAll("button")].find((b) => b.textContent.includes(wanted)).click(), name);
  const built = await uiResponse(page, "POST", `/billing/visits/${visit.id}/invoice/build`, () => click(page, "Build charges"));
  assert.equal(built.lines_added, 1);
  assert.equal(built.lines_skipped_unpriced, 1);
  await page.waitForFunction(() => document.querySelector("#main-content")?.textContent.includes("unpriced"));
  let detail = await billing.api("GET", `/billing/invoices/${preview.invoice_id}`);
  const line = detail.lines.find((l) => l.reference_id === items[0].id);
  assert.equal(line.unit_price, "413.27");
  assert.equal(line.charge_master_id, tariff.id, "Invoice read-back must retain the pinned tariff UUID");
  assert.ok(!detail.lines.some((l) => l.reference_id === items[1].id));
  await record(page, "UI build charges configured tariff; missing tariff is visible and not charged at zero");
  const again = await uiResponse(page, "POST", `/billing/visits/${visit.id}/invoice/build`, () => click(page, "Build charges"));
  assert.equal(again.lines_added, 0);
  assert.equal(again.gross_amount, built.gross_amount);
  await record(page, "Repeated UI build does not duplicate or reprice the original charge");
  // Resolve the deliberately missing test tariff before issue. This also
  // proves that an explicit zero is distinct from an unconfigured price.
  const freeTariff = await billing.api("POST", "/billing/charge-master", { charge_code: `${prefix}-missing`, charge_category: "radiology", description: "Synthetic explicitly free acceptance charge", unit_price: "0.00", effective_from: "2020-01-01" }, 201);
  const resolved = await uiResponse(page, "POST", `/billing/visits/${visit.id}/invoice/build`, () => click(page, "Build charges"));
  assert.equal(resolved.lines_added, 1);
  assert.equal(resolved.lines_skipped_unpriced, 0);
  detail = await billing.api("GET", `/billing/invoices/${preview.invoice_id}`);
  const freeLine = detail.lines.find((l) => l.reference_id === items[1].id);
  assert.equal(freeLine.unit_price, "0.00");
  assert.equal(freeLine.charge_master_id, freeTariff.id);
  await record(page, "Explicit zero tariff is billable and clears the missing-price warning before issue");
  await click(page, "Issue…");
  await uiResponse(page, "POST", `/billing/invoices/${preview.invoice_id}/issue`, () => click(page, "Issue invoice"));
  detail = await billing.api("GET", `/billing/invoices/${preview.invoice_id}`);
  assert.equal(detail.status, "issued");
  const due = detail.balance_due;
  await click(page, "Collect payment");
  await field(page, "Amount (₹)", due);
  const paid = await uiResponse(page, "POST", `/billing/invoices/${preview.invoice_id}/payments`, () => click(page, "Collect"), 201);
  assert.equal(paid.amount, due);
  detail = await billing.api("GET", `/billing/invoices/${preview.invoice_id}`);
  assert.equal(detail.status, "paid");
  assert.equal(detail.balance_due, "0.00");
  assert.equal(money(detail.net_amount), money(detail.total_paid) - money(detail.total_refunded));
  assert.equal(detail.lines.find((l) => l.id === line.id).charge_master_id, tariff.id);
  await record(page, "UI issue and full payment reconcile exact decimal amounts and preserve tariff provenance");
  const pharmacy = await role("dev.pharmacist", "/pharmacy/prescription-queue");
  await pharmacy.api("GET", `/billing/invoices/${preview.invoice_id}`, undefined, 403);
  await record(pharmacy.page, "Real pharmacist token is refused access to the mixed non-pharmacy invoice");
  report.passed = true;
  report.completed = true;
} catch (error) {
  report.failure = error.message;
  if (page) await page.screenshot({ path: path.join(evidenceDir, "tariff-failure.png"), fullPage: true }).catch(() => {});
  throw error;
} finally {
  await browser.close();
  await save();
}
