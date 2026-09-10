/** Local-only real API tariff workflow. Creates uniquely named synthetic rows;
 * never revises a pre-existing hospital tariff. Failure probes are explicit. */
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer";
import { baseUrl, click, field, login, open } from "./acceptance-support.mjs";

assert.equal(process.env.E2E_ALLOW_MUTATIONS, "1", "Opt in to synthetic local tariff writes");
const evidenceDir = process.env.E2E_EVIDENCE_DIR ?? "../docs/evidence/tariff-management";
await mkdir(evidenceDir, { recursive: true });
const code = `SYNTH-${randomUUID().slice(0, 18)}`;
const report = { runId: process.env.E2E_RUN_ID, baseUrl, code, completed: false, passed: false, checks: [] };
const save = () => writeFile(path.join(evidenceDir, "tariff-management.json"), JSON.stringify(report, null, 2));
await save();
const browser = await puppeteer.launch({ headless: true, acceptInsecureCerts: true,
  defaultViewport: { width: 1600, height: 1000 }, executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined, args: ["--no-sandbox"] });
let page, desk, posts = 0;
const writeRequests = [];
async function capture(name) {
  const screenshot = `tariffs__${report.checks.length + 1}.png`;
  await page.screenshot({ path: path.join(evidenceDir, screenshot), fullPage: true });
  report.checks.push({ name, passed: true, screenshot }); console.log(`PASS ${name}`); await save();
}
async function category() {
  await page.click('[role="dialog"] [role="combobox"]');
  await page.waitForSelector('[role="option"]');
  await page.evaluate(() => [...document.querySelectorAll('[role="option"]')].find((n) => n.textContent === "Lab").click());
}
async function fill(price, date, scheme = "") {
  await field(page, "Charge code", code); await field(page, "Description", "Synthetic tariff acceptance only");
  await category(); await field(page, "Unit price (₹)", price);
  await field(page, "Effective from", date); await field(page, "Scheme code (optional)", scheme);
}
async function saveVersion(expected = 201) {
  await click(page, "Review tariff");
  const response = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/v1/billing/charge-master" && r.request().method() === "POST");
  await click(page, "Save tariff version"); assert.equal((await response).status(), expected);
  if (expected === 201) {
    await page.waitForFunction(() => !document.querySelector('[role="dialog"]'));
    await page.waitForSelector('table[aria-label="Tariff versions"]');
  }
}
async function rowAction(date, label) {
  await page.waitForFunction((wanted) => [...document.querySelectorAll("tbody tr")].some((r) => r.textContent.includes(wanted)), {}, date);
  await page.evaluate((date, label) => {
    const row = [...document.querySelectorAll("tbody tr")].find((r) => r.textContent.includes(date) && r.textContent.includes("General"));
    const action = [...row.querySelectorAll("button")].find((b) => b.textContent.trim() === label);
    if (!action) throw new Error(`Missing ${label}`); action.click();
  }, date, label);
}
const tariffs = () => desk.api("GET", `/billing/charge-master?charge_code=${encodeURIComponent(code)}&active_only=false`);

try {
  desk = await login(browser, "dev.billing"); page = desk.page;
  page.on("request", (r) => {
    if (new URL(r.url()).pathname.startsWith("/api/v1/billing/charge-master")) {
      assert.match(r.headers().authorization ?? "", /^Bearer /);
      if (r.method() === "POST") {
        posts++;
        writeRequests.push({ path: new URL(r.url()).pathname.replace("/api/v1", ""),
          body: r.postData() ? JSON.parse(r.postData()) : undefined,
          key: r.headers()["idempotency-key"] });
      }
    }
  });
  await open(page, "/billing/tariffs"); await page.waitForSelector('table[aria-label="Tariff versions"]');
  assert.equal(await page.$$eval('#workspace-sidebar [aria-current="page"]', (nodes) => nodes.length), 1);
  await field(page, "Search code, description or scheme", code);
  await click(page, "New tariff"); await click(page, "Review tariff");
  await page.waitForFunction(() => document.querySelector('[role="dialog"]').textContent.includes("Enter a charge code."));
  assert.equal(posts, 0); await capture("Invalid tariff form displays field errors without sending a mutation");
  await fill("71.23", "2030-01-10"); await saveVersion();
  let rows = await tariffs(); assert.equal(rows.length, 1); assert.equal(rows[0].unit_price, "71.23");
  const originalId = rows[0].id;
  await capture("Billing creates an exact-decimal general tariff through the real API");

  const creation = writeRequests[0]; assert.ok(creation.key);
  const replayed = await desk.api("POST", creation.path, creation.body, 201, { "Idempotency-Key": creation.key });
  assert.equal(replayed.id, originalId); assert.equal((await tariffs()).length, 1);
  await desk.api("POST", creation.path, { ...creation.body, unit_price: "99.00" }, 409, { "Idempotency-Key": creation.key });
  await capture("Exact browser request replay returns its original tariff; changed-body key reuse is refused");

  await rowAction("2030-01-10", "Revise");
  await field(page, "Unit price (₹)", "81.45"); await field(page, "Effective from", "2030-01-12");
  await saveVersion(); rows = await tariffs();
  assert.equal(rows.length, 2); assert.equal(rows.find((r) => r.id === originalId).effective_to, "2030-01-11");
  assert.equal(rows.find((r) => r.id === originalId).unit_price, "71.23");
  const replacement = rows.find((r) => r.id !== originalId); assert.equal(replacement.unit_price, "81.45");
  await capture("Revision creates a new row and preserves the original price with an inclusive end date");

  await click(page, "New tariff"); await fill("0", "2030-01-10", "SYNTH-SCHEME"); await saveVersion();
  rows = await tariffs(); assert.equal(rows.length, 3);
  assert.equal(rows.find((r) => r.scheme_code === "SYNTH-SCHEME").unit_price, "0.00");
  await capture("Explicit zero-priced scheme tariff is distinct from the general rate");

  await click(page, "New tariff"); await fill("72.00", "2030-01-10", "SYNTH-SCHEME"); await saveVersion(409);
  await page.waitForSelector('[role="dialog"] [role="alert"]');
  assert.ok(!(await page.$eval('[role="dialog"]', (n) => n.textContent)).includes("Save tariff version"));
  assert.equal((await tariffs()).length, 3);
  await capture("Server date conflict remains visible and prevents a speculative retry");
  await click(page, "Close and check catalogue"); await page.waitForSelector('table[aria-label="Tariff versions"]');

  await rowAction("2030-01-12", "Retire");
  const retired = page.waitForResponse((r) => new URL(r.url()).pathname.endsWith(`/${replacement.id}/deactivate`));
  await click(page, "Confirm retirement"); assert.equal((await retired).status(), 204);
  await page.waitForFunction(() => !document.querySelector('[role="dialog"]'));
  await page.waitForSelector('table[aria-label="Tariff versions"]');
  assert.equal((await tariffs()).find((r) => r.id === replacement.id).is_active, false);
  const retirement = writeRequests.find((r) => r.path.endsWith(`/${replacement.id}/deactivate`));
  assert.ok(retirement.key);
  await desk.api("POST", retirement.path, undefined, 204, { "Idempotency-Key": retirement.key });
  const historyRead = page.waitForResponse((r) => r.request().method() === "GET" && r.url().includes("charge-master?active_only=false"));
  await page.evaluate(() => [...document.querySelectorAll("label")].find((l) => l.textContent.includes("Include retired tariffs")).click());
  await historyRead; await page.waitForFunction(() => document.querySelector("tbody")?.textContent.includes("Retired"));
  await capture("Retirement and exact retry both return bodyless 204; history remains retained");

  let failRead = true;
  await page.setRequestInterception(true);
  page.on("request", (request) => {
    if (failRead && request.method() === "GET" && new URL(request.url()).pathname === "/api/v1/billing/charge-master") {
      return void request.respond({ status: 503, contentType: "application/json", body: JSON.stringify({ success: false, data: null, error: { code: 503, message: "Synthetic outage" }, meta: {} }) });
    }
    void request.continue();
  });
  await click(page, "Reload catalogue");
  await page.waitForFunction(() => [...document.querySelectorAll('#main-content [role="alert"]')].some((n) => n.textContent.includes("Use Reload catalogue to retry")));
  assert.equal(await page.$('table[aria-label="Tariff versions"]'), null);
  await capture("Catalogue failure is not displayed as empty history or stale success");
  failRead = false; await click(page, "Reload catalogue"); await page.waitForSelector('table[aria-label="Tariff versions"]');

  const admin = await login(browser, "dev.admin"); page = admin.page;
  await open(page, "/billing/tariffs"); await page.waitForSelector('table[aria-label="Tariff versions"]');
  await field(page, "Search code, description or scheme", code);
  await rowAction("2030-01-10", "Retire");
  const adminRetired = page.waitForResponse((r) => new URL(r.url()).pathname.endsWith(`/${originalId}/deactivate`));
  await click(page, "Confirm retirement"); assert.equal((await adminRetired).status(), 204);
  await page.waitForFunction(() => !document.querySelector('[role="dialog"]'));
  await page.waitForSelector('table[aria-label="Tariff versions"]');
  const adminHistory = await admin.api("GET", `/billing/charge-master?charge_code=${encodeURIComponent(code)}&active_only=false`);
  assert.equal(adminHistory.find((r) => r.id === originalId).is_active, false);
  assert.equal(adminHistory.find((r) => r.id === originalId).unit_price, "71.23");
  await capture("Independent facility admin retires a synthetic version without deleting or changing its historical price");
  await admin.context.close();

  const reception = await login(browser, "dev.receptionist"); page = reception.page;
  await page.goto(`${baseUrl}/billing/tariffs`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => location.pathname.startsWith("/receptionist/"));
  await page.waitForSelector("#main-content");
  assert.equal(await page.$('a[href="/billing/tariffs"]'), null);
  await reception.api("GET", "/billing/charge-master", undefined, 403);
  await reception.api("POST", "/billing/charge-master", { charge_code: code, description: "Must be refused", charge_category: "lab", unit_price: "1.00", effective_from: "2030-01-20" }, 403);
  await reception.api("POST", `/billing/charge-master/${originalId}/deactivate`, undefined, 403);
  await capture("Reception is denied tariff navigation, catalogue reads and both write routes");
  await reception.context.close();
  report.completed = true; report.passed = true;
} catch (error) {
  report.failure = error.message;
  if (page) await page.screenshot({ path: path.join(evidenceDir, "tariffs-failure.png"), fullPage: true }).catch(() => {});
  throw error;
} finally { await browser.close(); await save(); }
