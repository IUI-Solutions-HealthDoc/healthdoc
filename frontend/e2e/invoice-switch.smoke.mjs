/** Real Keycloak/rendered UI; all billing data and mutations are intercepted.
 * This injects response races, not real payments or an ABDM round trip.
 */
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer";
import { baseUrl, click, field, login, open } from "./acceptance-support.mjs";

const evidenceDir = process.env.E2E_EVIDENCE_DIR ?? "../docs/evidence/invoice-switch";
await mkdir(evidenceDir, { recursive: true });
const report = { runId: process.env.E2E_RUN_ID, baseUrl, completed: false, passed: false,
  transport: "Real Keycloak; simulated billing reads and writes; no financial mutation reaches the server", checks: [] };
const save = () => writeFile(path.join(evidenceDir, "invoice-switch.json"), JSON.stringify(report, null, 2));
await save();
const rows = ["Alpha", "Beta", "Gamma", "Delta"].map((label, index) => {
  const id = randomUUID(), amount = ["50.00", "71.23", "99.00", "150.00"][index];
  return { label, id, invoice_number: `INV-SYNTHETIC-${label}`, patient_id: randomUUID(),
    patient_full_name: `Synthetic Invoice ${label}`, patient_identifier: `SYNTHETIC-${label}`,
    visit_id: randomUUID(), facility_id: randomUUID(), status: index < 2 ? "issued" : "draft",
    gross_amount: amount, net_amount: amount, discount_amount: "0.00", scheme_adjustment: "0.00",
    scheme_code: null, row_version: 1, created_at: "2026-09-09T00:00:00Z", payments: [],
    total_paid: "0.00", total_refunded: "0.00", balance_due: amount,
    lines: [{ id: randomUUID(), invoice_id: id, charge_category: "registration", reference_type: null,
      reference_id: null, charge_master_id: null, description: "Synthetic only", quantity: "1.00", unit_price: amount, amount }] };
});
const browser = await puppeteer.launch({ headless: true, acceptInsecureCerts: true,
  defaultViewport: { width: 1440, height: 1000 }, executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
  args: ["--no-sandbox"] });
let page;
const pending = [], unexpected = [], mutations = [];
let holdRead = "Alpha", failRead = null, holdMutation = null;
function json(request, data, status = 200) {
  return request.respond({ status, contentType: "application/json", body: JSON.stringify(status < 400
    ? { success: true, data, error: null, meta: {} }
    : { success: false, data: null, error: { code: "SYNTHETIC_FAILURE", message: "Invoice unavailable. Try again." }, meta: {} }) });
}
async function select(label) {
  const name = `Synthetic Invoice ${label}`;
  await page.waitForFunction((wanted) => [...document.querySelectorAll("#main-content button")].some((b) => b.textContent.includes(wanted)), {}, name);
  // Also deliberately forces selection while a modal is open: a state-change
  // stress test, not a claim a mouse can click through the modal backdrop.
  await page.evaluate((wanted) => [...document.querySelectorAll("#main-content button")].find((b) => b.textContent.includes(wanted)).click(), name);
}
async function header() {
  return page.evaluate(() => [...document.querySelectorAll("#main-content p")].find((p) => p.textContent.startsWith("UHID SYNTHETIC-"))?.parentElement?.textContent ?? "");
}
async function waitInvoice(label) {
  await page.waitForFunction((wanted) => [...document.querySelectorAll("#main-content p")].some((p) => p.textContent.startsWith(`UHID SYNTHETIC-${wanted}`)), {}, label);
}
async function settle() {
  await page.evaluate(() => new Promise((resolve) => setTimeout(() => requestAnimationFrame(() => requestAnimationFrame(resolve)), 150)));
}
async function release(kind) {
  const selected = pending.filter((p) => p.kind === kind);
  assert.ok(selected.length > 0, `Must actually delay ${kind}`);
  for (const item of selected) pending.splice(pending.indexOf(item), 1);
  await Promise.all(selected.map((p) => p.run()));
  await settle();
}
async function record(name) {
  assert.deepEqual(unexpected, []);
  const screenshot = `invoice-switch__${report.checks.length + 1}.png`;
  await page.screenshot({ path: path.join(evidenceDir, screenshot), fullPage: true });
  report.checks.push({ name, passed: true, screenshot });
  console.log(`PASS ${name}`);
  await save();
}
try {
  ({ page } = await login(browser, "dev.billing"));
  await page.setRequestInterception(true);
  page.on("request", (request) => {
    const route = new URL(request.url()).pathname;
    if (!route.startsWith("/api/v1/billing/")) return void request.continue();
    assert.match(request.headers().authorization ?? "", /^Bearer /);
    if (request.method() === "GET" && route === "/api/v1/billing/invoices") return void json(request, { items: rows, total: rows.length, page: 1, page_size: 20 });
    const row = rows.find((r) => route === `/api/v1/billing/invoices/${r.id}`);
    if (row && request.method() === "GET") {
      const data = structuredClone(row), status = failRead === row.label ? 503 : 200;
      if (holdRead === row.label) pending.push({ kind: "read", run: () => json(request, data, status) });
      else void json(request, data, status);
      return;
    }
    const invoice = rows.find((r) => route === `/api/v1/billing/invoices/${r.id}/payments`
      || route === `/api/v1/billing/invoices/${r.id}/issue` || route === `/api/v1/billing/visits/${r.visit_id}/invoice/build`);
    if (invoice && request.method() === "POST") {
      const kind = route.endsWith("/build") ? "build" : route.endsWith("/issue") ? "issue" : "payment";
      mutations.push({ kind, invoice: invoice.label, body: request.postData() ? JSON.parse(request.postData()) : null });
      const run = () => {
        invoice.row_version++;
        if (kind === "build") return json(request, { invoice_id: invoice.id, lines_added: 1, lines_skipped_unpriced: 0, gross_amount: invoice.gross_amount });
        if (kind === "issue") { invoice.status = "issued"; return json(request, invoice); }
        assert.equal(invoice.label, "Alpha");
        assert.equal(mutations.at(-1).body.amount, "1.00");
        invoice.total_paid = "1.00"; invoice.balance_due = "49.00"; invoice.status = "partially_paid";
        const receipt = { id: randomUUID(), invoice_id: invoice.id, amount: "1.00", mode: "cash", status: "success", receipt_number: "RCP-SYNTHETIC-ALPHA", refunds: [], collected_by: "Synthetic only" };
        invoice.payments = [receipt];
        return json(request, receipt, 201);
      };
      if (holdMutation === kind) pending.push({ kind, run }); else void run();
      return;
    }
    unexpected.push(`${request.method()} ${route}`);
    void request.abort(); // Never let an unexpected billing write reach the app.
  });
  await open(page, "/billing");
  const alphaRequest = page.waitForRequest((r) => new URL(r.url()).pathname.endsWith(rows[0].id));
  await select("Alpha");
  await alphaRequest;
  await select("Beta"); await waitInvoice("Beta");
  await release("read");
  assert.match(await header(), /Synthetic Invoice Beta/, "Late Alpha detail must not replace the selected Beta invoice");
  await record("Late invoice details cannot replace the newly selected invoice");

  holdRead = null;
  await select("Alpha"); await waitInvoice("Alpha");
  holdRead = "Beta";
  await click(page, "Collect payment"); await field(page, "Amount (₹)", "3.00");
  await select("Beta"); await settle();
  assert.equal(await header(), "", "Old invoice must clear while Beta loads");
  assert.equal(await page.$('[role="dialog"]'), null, "Collection dialog must close on selection change");
  holdRead = null; // Follow-up balance reads must not remain artificially held.
  await release("read"); await waitInvoice("Beta");
  await click(page, "Collect payment");
  assert.equal(await page.$eval('[role="dialog"] input[type="number"]', (n) => n.value), "71.23");
  await click(page, "Cancel");
  await record("Invoice switch clears old controls and resets collection amount for the new invoice");

  holdRead = null; failRead = "Delta";
  await select("Delta");
  await page.waitForSelector('[role="alert"]');
  assert.equal(await header(), "");
  await record("Failed selected-invoice read remains visible without another invoice's payment controls");
  failRead = null;
  await click(page, "Retry invoice"); await waitInvoice("Delta");
  await record("Failed invoice read can be retried without reselecting a different patient");

  await select("Gamma"); await waitInvoice("Gamma");
  holdMutation = "build";
  const buildRequest = page.waitForRequest((r) => new URL(r.url()).pathname.endsWith("/invoice/build"));
  await click(page, "Build charges"); await buildRequest;
  await select("Beta"); await waitInvoice("Beta");
  await release("build");
  assert.match(await header(), /Synthetic Invoice Beta/);
  assert.ok(!(await page.$eval("#main-content", (n) => n.textContent)).includes("1 charge(s) added"));
  await record("Late build completion cannot replace the current invoice or its status message");

  await select("Gamma"); await waitInvoice("Gamma");
  holdMutation = "issue";
  await click(page, "Issue…");
  const issueRequest = page.waitForRequest((r) => new URL(r.url()).pathname.endsWith("/issue"));
  await click(page, "Issue invoice"); await issueRequest;
  await select("Beta"); await waitInvoice("Beta");
  await release("issue");
  assert.match(await header(), /Synthetic Invoice Beta/);
  assert.equal(await page.$('[role="dialog"]'), null);
  await record("Late issue completion and preview dialog remain isolated to their original invoice");

  await select("Alpha"); await waitInvoice("Alpha");
  holdMutation = "payment";
  await click(page, "Collect payment"); await field(page, "Amount (₹)", "1.00");
  const paymentRequest = page.waitForRequest((r) => new URL(r.url()).pathname.endsWith("/payments") && r.method() === "POST");
  await click(page, "Collect"); await paymentRequest;
  await select("Beta"); await waitInvoice("Beta");
  await release("payment");
  assert.match(await header(), /Synthetic Invoice Beta/);
  assert.equal(rows[1].total_paid, "0.00");
  assert.equal(mutations.filter((m) => m.kind === "payment").length, 1);
  await record("Late payment response stays on its original invoice and never charges the new selection");
  report.completed = true; report.passed = true;
} catch (error) {
  report.failure = error.message;
  if (page) await page.screenshot({ path: path.join(evidenceDir, "invoice-switch-failure.png"), fullPage: true }).catch(() => {});
  throw error;
} finally {
  await browser.close(); await save();
}
