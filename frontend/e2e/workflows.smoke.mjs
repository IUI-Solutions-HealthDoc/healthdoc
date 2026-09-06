/** Real UI mutations against an explicitly opted-in LOCAL development stack.
 * No API mocking, direct token grants, real patient records, or external ABDM
 * calls. Synthetic records are retained for inspection; never run on production.
 */
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer";

const baseUrl = process.env.E2E_BASE_URL ?? "https://localhost";
assert(["localhost", "127.0.0.1", "[::1]"].includes(new URL(baseUrl).hostname));
assert.equal(process.env.E2E_ALLOW_MUTATIONS, "1", "Set E2E_ALLOW_MUTATIONS=1 for synthetic local records");
const requested = process.env.E2E_WORKFLOW;
const allowRecovery = process.env.E2E_ALLOW_RECOVERY === "1";

/**
 * Evidence capture, as in dashboards.smoke.mjs: the image is taken only after
 * the assertions above it have already passed, so it records a proven state
 * rather than standing in for the proof.
 */
const evidenceDir = process.env.E2E_EVIDENCE_DIR;
const evidence = [];
const runId = process.env.E2E_RUN_ID;
const workflowResults = [];
const warnings = [];
let currentWorkflow;
let currentUsername;
if (evidenceDir) {
  await mkdir(evidenceDir, { recursive: true });
  // Invalidate the previous successful run before login or browser launch can
  // fail. A crash must not leave yesterday's PASS looking current.
  await writeFile(path.join(evidenceDir, "workflows.json"), JSON.stringify({
    runId, baseUrl, completed: false, fullRun: !requested, recoveryAllowed: allowRecovery, steps: [],
  }));
}

async function record(page, { role, name, detail }) {
  if (!evidenceDir) return;
  const file = `workflow__${role}__${name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}.png`;
  await mkdir(evidenceDir, { recursive: true });
  await page.addStyleTag({ content: "nextjs-portal{display:none!important}" });
  await page.screenshot({ path: path.join(evidenceDir, file), fullPage: true });
  evidence.push({ role, name, detail, workflow: currentWorkflow, passed: true, failures: [], screenshot: file, capturedAt: new Date().toISOString() });
}
const browser = await puppeteer.launch({
  headless: true,
  acceptInsecureCerts: true,
  defaultViewport: { width: 1440, height: 900 },
  executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
  args: ["--no-sandbox"],
});

async function text(page, value) {
  await page.waitForFunction((wanted) => document.querySelector("#main-content")?.textContent?.includes(wanted), { timeout: 30_000 }, value);
}

async function click(page, label) {
  await page.waitForFunction((wanted) => [...document.querySelectorAll("button")].some((b) => b.textContent?.trim() === wanted && !b.disabled), { timeout: 30_000 }, label);
  await page.evaluate((wanted) => {
    const buttons = [...document.querySelectorAll("button")].filter((b) => b.textContent?.trim() === wanted && !b.disabled);
    if (buttons.length !== 1) throw new Error(`Expected one enabled button: ${wanted}`);
    buttons[0].click();
  }, label);
}

async function field(page, label, value) {
  await page.evaluate((wanted, next) => {
    const labels = [...document.querySelectorAll("#main-content label")];
    const parent = labels.find((l) => l.querySelector("span")?.textContent?.trim() === wanted);
    const input = parent?.querySelector("input,select,textarea");
    if (!input) throw new Error(`Missing field: ${wanted}`);
    const prototype = input instanceof HTMLSelectElement ? HTMLSelectElement.prototype : input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value").set.call(input, next);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }, label, value);
}

async function muiField(page, label, value) {
  await page.waitForFunction((wanted) => [...document.querySelectorAll("label")].some((l) => l.textContent?.trim() === wanted && l.control), { timeout: 30_000 }, label);
  await page.evaluate((wanted, next) => {
    const control = [...document.querySelectorAll("label")].find((l) => l.textContent?.trim() === wanted)?.control;
    if (!control) throw new Error(`Missing labelled input: ${wanted}`);
    const prototype = control instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value").set.call(control, next);
    control.dispatchEvent(new Event("input", { bubbles: true }));
  }, label, value);
}

async function muiSelect(page, label, value) {
  await page.waitForSelector('[role="dialog"] [role="combobox"]', { timeout: 30_000 });
  await page.evaluate((wanted) => {
    // MUI 9 can render a select's accessible label as a span. Follow ARIA
    // associations rather than assuming a native <label> ancestor exists.
    const controls = [...document.querySelectorAll('[role="dialog"] [role="combobox"]')];
    const accessibleName = (control) => control.getAttribute("aria-label") ?? (control.getAttribute("aria-labelledby") ?? "").split(/\s+/).map((id) => document.getElementById(id)?.textContent?.trim() ?? "").join(" ").trim();
    const select = controls.find((c) => accessibleName(c) === wanted);
    if (!select) throw new Error(`Missing select: ${wanted}; names: ${controls.map(accessibleName).join(", ")}`);
    select.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
  }, label);
  await page.waitForSelector(`[role="option"][data-value="${value}"]`);
  await page.click(`[role="option"][data-value="${value}"]`);
}

async function openAccession(page, accession) {
  await page.waitForFunction((wanted) => [...document.querySelectorAll("#main-content tbody tr")].some((r) => r.textContent.includes(wanted)), { timeout: 30_000 }, accession);
  await page.evaluate((wanted) => {
    const row = [...document.querySelectorAll("#main-content tbody tr")].find((r) => r.textContent.includes(wanted));
    (row.querySelector("button") ?? row).click();
  }, accession);
}

function localDateTime(date = new Date()) {
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

// These department APIs use locked status transitions instead of idempotency
// headers. Assert the actual resulting state; don't weaken responseTo's gate
// for unrelated creates/payments that DO require retry keys.
async function transitionResponse(page, method, path, action, state, status = 200) {
  const pending = page.waitForResponse((r) => r.request().method() === method && new URL(r.url()).pathname === `/api/v1${path}`, { timeout: 30_000 });
  const [response] = await Promise.all([pending, action()]);
  assert.equal(response.status(), status, `${method} ${path}`);
  assert.match(response.request().headers().authorization ?? "", /^Bearer /);
  const body = await response.json();
  const data = body.data ?? body;
  assert.equal(data.status, state, `${path} resulting state`);
  return data;
}

/** react-hook-form screens render `id="field-<name>"` and no label span. */
async function setById(page, id, value) {
  await page.waitForSelector(`#${id}`, { timeout: 30_000 });
  await page.evaluate((fieldId, next) => {
    const input = document.getElementById(fieldId);
    if (!input) throw new Error(`Missing field: ${fieldId}`);
    const prototype = input instanceof HTMLSelectElement
      ? HTMLSelectElement.prototype
      : input instanceof HTMLTextAreaElement
        ? HTMLTextAreaElement.prototype
        : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value").set.call(input, next);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }, id, value);
}

async function responseTo(page, method, path, action, status = 200) {
  const responsePromise = page.waitForResponse((r) => r.request().method() === method && new URL(r.url()).pathname === `/api/v1${path}`, { timeout: 30_000 });
  const [response] = await Promise.all([responsePromise, action()]);
  assert.equal(response.status(), status, `${method} ${path}`);
  assert.match(response.request().headers().authorization ?? "", /^Bearer /);
  if (method !== "GET") {
    // Two mechanisms, both real. Creates carry an Idempotency-Key so a retried
    // POST replays instead of duplicating; updates carry If-Match so a retried
    // PATCH against a moved row is refused 412 rather than silently clobbering
    // it. PATCH /encounters/{id} mandates If-Match and 428s without one, so
    // demanding an Idempotency-Key there fails a correctly protected call.
    const headers = response.request().headers();
    assert.ok(
      headers["idempotency-key"] || headers["if-match"],
      `${path}: mutation carries neither an Idempotency-Key nor an If-Match`,
    );
  }
  const body = await response.json();
  return body.data ?? body;
}

async function open(page, path) {
  // Recovery is diagnostic-only, just as it is for login and the screen gate.
  for (let attempt = 1; attempt <= 2; attempt += 1) {
    try {
      await page.goto(`${baseUrl}${path}`, { waitUntil: "domcontentloaded", timeout: 60_000 });
      await page.waitForSelector("#main-content", { timeout: 60_000 });
      break;
    } catch (error) {
      if (!allowRecovery || attempt === 2) throw error;
      warnings.push({ role: currentUsername ?? "public", workflow: currentWorkflow,
        pathname: new URL(page.url()).pathname, message: `Navigation to ${path} did not settle; retried once` });
      console.warn(`${path} — did not settle; diagnostic retry requested`);
    }
  }
  assert.equal(new URL(page.url()).pathname, path);
}

async function withRole(username, run) {
  currentUsername = username;
  console.log(`RUN ${currentWorkflow}: ${username}`);
  const context = await browser.createBrowserContext();
  let page = await context.newPage();
  const errors = [];
  const captureError = (error) => errors.push(error.message);
  page.on("pageerror", captureError);

  // Capture the real access token from the Keycloak exchange, the same way
  // superadmin-isolation.smoke.mjs does. A raw fetch() from the page carries
  // no Authorization header, so asserting on its status would only prove that
  // anonymous requests are refused — which is not a statement about this
  // role at all.
  let accessToken = null;
  const captureToken = async (response) => {
    if (!new URL(response.url()).pathname.endsWith("/protocol/openid-connect/token")) return;
    try {
      const body = await response.json();
      if (body.access_token) accessToken = body.access_token;
    } catch {
      // Not every token-endpoint response is JSON we can read; ignore.
    }
  };
  page.on("response", captureToken);
  try {
    await page.goto(`${baseUrl}/login`, { waitUntil: "domcontentloaded" });
    await click(page, "Sign in with Keycloak");
    await page.waitForSelector("#username");
    await page.type("#username", username);
    await page.type("#password", "devpass");
    const [loginResponse] = await Promise.all([
      page.waitForResponse((response) => response.request().method() === "POST"
        && new URL(response.url()).pathname.includes("/login-actions/authenticate")),
      page.click("#kc-login"),
    ]);
    assert.ok(loginResponse.status() < 400, `Keycloak login submission returned HTTP ${loginResponse.status()}`);
    try {
      // MainLayout also renders #main-content on the authenticated root page.
      // Its role redirect can still be pending there. Starting a new goto at
      // that instant races the root's router.replace and can navigate us back
      // to the landing page in the middle of a workflow.
      await page.waitForFunction(() => {
        const pathname = window.location.pathname;
        return pathname !== "/" && pathname !== "/login" && !pathname.startsWith("/auth/");
      }, { timeout: 60_000 });
      await page.waitForSelector("#main-content", { timeout: 60_000 });
    } catch (error) {
      if (!allowRecovery) throw error;
      // Capture the stalled landing before the one permitted recovery. A
      // reload recovering it does not establish its cause or prove a clean
      // first load; keep this visible in the generated evidence report.
      const state = await page.evaluate(() => ({
        pathname: window.location.pathname,
        readyState: document.readyState,
        loadingWorkspace: document.body.textContent.includes("Loading your workspace"),
      }));
      warnings.push({ role: username, workflow: currentWorkflow, message: "Landing content missing after 60 seconds; reloaded once", ...state });
      console.warn(`[${username}] login did not reach workspace content; diagnostic reload requested`);
      await page.reload({ waitUntil: "domcontentloaded", timeout: 60_000 });
      await page.waitForSelector("#main-content", { timeout: 60_000 });
    }
    // Keep login's initial API reads in their own tab. A new goto on that
    // tab could abort a body while responseTo was reading it (especially the
    // patient portal's four mount reads). The workflow tab shares real SSO,
    // not injected tokens, and its response observers see only its own reads.
    page = await context.newPage();
    page.on("pageerror", captureError);
    page.on("response", captureToken);
    try {
      await run(page, { token: () => accessToken });
    } catch (error) {
      // A timeout tells you nothing about which control was missing. Record
      // where the run actually was so the next reader diagnoses instead of
      // re-running it blind.
      if (evidenceDir) {
        await mkdir(evidenceDir, { recursive: true });
        const file = `failure__${username}__${Date.now()}.png`;
        await page.screenshot({ path: path.join(evidenceDir, file), fullPage: true }).catch(() => {});
        const heading = await page.evaluate(() => document.querySelector("#main-content h1,#main-content h2")?.textContent?.trim() ?? null).catch(() => null);
        // Capped: a data-dense screen can hold hundreds of row buttons, and an
        // unbounded dump buries the one line that explains the failure.
        const buttons = await page.evaluate(() => [...document.querySelectorAll("#main-content button")]
          .map((b) => b.textContent?.trim().slice(0, 60)).filter(Boolean).slice(0, 25)).catch(() => []);
        // Validation messages, not just controls: a form that refuses to submit
        // is usually rejecting a field, and react-hook-form renders the reason
        // next to it — unless the field is not rendered at all, in which case
        // the empty list here is itself the finding.
        const validation = await page.evaluate(() => [...document.querySelectorAll('#main-content .text-danger, #main-content [role="alert"]')].map((n) => n.textContent?.trim()).filter(Boolean)).catch(() => []);
        console.error(`  at ${new URL(page.url()).pathname} — heading ${JSON.stringify(heading)}; buttons: ${JSON.stringify(buttons)}`);
        console.error(`  validation messages: ${JSON.stringify(validation)}; capture ${file}`);
      }
      throw error;
    }
    assert.deepEqual(errors, [], "Uncaught browser errors");
  } finally {
    await context.close();
  }
}

const workflows = {
  async inventory() {
    await withRole("dev.pharmacist", async (page) => {
      await open(page, "/inventory");
      for (const [tab, path] of [["Goods receipt", "/pharmacy/grn"], ["Transfers", "/inventory/stock-transfers"], ["Indents", "/pharmacy/indents"], ["Adjustments", "/pharmacy/adjustments"]]) {
        await responseTo(page, "GET", path, () => click(page, tab));
        assert.equal(await page.$$eval('[role="alert"]', (nodes) => nodes.length), 0, tab);
        await record(page, { role: "pharmacist", name: `Inventory — ${tab}`, detail: `Tab loaded \`GET ${path}\` with a bearer token and rendered no error state.` });
      }
      // Exactly this path. Accepting /api/v1/users as an alternative is what
      // let the original defect through: that route is gated `admin`, so a
      // pharmacist got 403 and the screen's catch turned it into "no such
      // colleague".
      const response = page.waitForResponse((r) => r.request().method() === "GET" && new URL(r.url()).pathname === "/api/v1/pharmacy/adjustment-candidates");
      await page.type('input[placeholder="Search staff…"]', "Dev");
      assert.equal((await response).status(), 200, "Pharmacist must be able to find a first approver");
      await text(page, "Dev Admin");
      await record(page, { role: "pharmacist", name: "Inventory — approver lookup", detail: "Staff search returned a first approver, so an adjustment can actually be routed for maker-checker approval." });
    });
  },
  async maintenance() {
    for (const username of ["dev.labtech", "dev.radiology", "dev.admin"]) {
      await withRole(username, async (page) => {
        await open(page, "/admin/maintenance");
        const machine = `E2E-${randomUUID().slice(0, 8)}`;
        // Wait for the Department select specifically. `select:first-of-type`
        // matched every select on the page, because each one is the only
        // select inside its own label — so this wait was satisfied by the
        // static "Type" dropdown while departments were still loading, and
        // the read below raced it.
        await page.waitForFunction(() => {
          const label = [...document.querySelectorAll("#main-content label")]
            .find((l) => l.querySelector("span")?.textContent?.trim() === "Department");
          return (label?.querySelectorAll('option[value]:not([value=""])').length ?? 0) > 0;
        }, { timeout: 30_000 });
        const department = await page.evaluate(() => [...document.querySelectorAll("label")].find((l) => l.querySelector("span")?.textContent === "Department")?.querySelector('option[value]:not([value=""])')?.value);
        assert.ok(department, "Seeded department required");
        await field(page, "Machine", machine);
        await field(page, "Department", department);
        await field(page, "Performed at", localDateTime());
        await field(page, "Notes", "Synthetic browser verification — no real equipment service.");
        const saved = await responseTo(page, "POST", "/maintenance/logs", () => click(page, "Record service"), 201);
        assert.equal(saved.machine_id, machine);
        assert.equal(saved.downtime_minutes, null);
        await text(page, machine);
        await page.reload({ waitUntil: "domcontentloaded" });
        await text(page, machine);
        await page.type('input[placeholder="Filter by machine…"]', machine);
        await page.waitForFunction((wanted) => {
          const rows = [...document.querySelectorAll("#main-content li")];
          return rows.length === 1 && rows[0].textContent.includes(wanted) && rows[0].textContent.includes("Downtime: not recorded");
        }, {}, machine);
        await record(page, { role: username.replace("dev.", "").replace("labtech", "lab_tech").replace("radiology", "radiology_tech"), name: "Equipment maintenance — record service", detail: `Created service log \`${machine}\`, confirmed it survived a full page reload, filtered to exactly that row, and confirmed unrecorded downtime is stored as null rather than zero.` });
        console.log(`PASS ${username}: create, persisted reload, exact filter, null downtime`);
      });
    }
  },
  /**
   * Emergency THID, then the maker-checker promotion to a permanent UHID.
   *
   * Needs two supervisors and always did: the approver must not be the
   * requester and the unmerger must not be the approver. With one seeded
   * supervisor account the only reachable outcome was the refusal, so the
   * approve and unmerge halves had never been exercised by anybody — which is
   * why scripts/dev_setup.sh now provisions dev.supervisor2.
   */
  async emergency_and_merge() {
    let patientId = null;
    let thid = null;

    await withRole("dev.emergency", async (page) => {
      await open(page, "/emergency");
      await field(page, "Name (leave blank if unknown)", `Emergency Test ${randomUUID().replace(/[0-9-]/g, "a")}`);
      await field(page, "Sex", "female");
      await field(page, "Estimated age (years)", "34");
      const created = await responseTo(page, "POST", "/emergency/patients", () => click(page, "Register and issue THID"), 201);
      patientId = created.id;
      thid = created.thid;
      assert.ok(thid, "An emergency registration must issue a temporary identity");
      assert.equal(created.identity_path, "thid");
      await text(page, thid);
      await record(page, { role: "emergency", name: "Emergency — register and issue a THID", detail: `Registered an unidentified arrival and issued temporary identity \`${thid}\`. No name, ABHA or ID is required to get a patient into the system.` });
    });

    let mergeLogId = null;
    await withRole("dev.supervisor", async (page) => {
      await open(page, "/supervisor/merges");
      await field(page, "Patient ID", patientId);
      await field(page, "Reason (optional)", "Identity confirmed at the desk. Synthetic verification.");
      const log = await responseTo(page, "POST", `/emergency/patients/${patientId}/promote`, () => click(page, "Request promotion"), 201);
      mergeLogId = log.id;
      assert.equal(log.status, "pending");
      await text(page, mergeLogId);
      await record(page, { role: "supervisor", name: "Identity merges — request THID→UHID promotion", detail: "Raised the promotion request. It stays pending until a different supervisor approves it, which is the whole point of the control." });

      // The maker-checker rule itself. Approving your own request must fail.
      await click(page, "2. Approve");
      await field(page, "Merge log ID", mergeLogId);
      const responsePromise = page.waitForResponse((r) => r.request().method() === "POST" && new URL(r.url()).pathname === `/api/v1/emergency/patients/promotions/${mergeLogId}/approve`, { timeout: 30_000 });
      await click(page, "Confirm and assign UHID");
      const refused = await responsePromise;
      assert.equal(refused.status(), 409, "Self-approval must be denied by the maker-checker rule, not a server error");
      const refusal = await refused.json();
      assert.ok(JSON.stringify(refusal).includes('"self_approval_not_allowed"'), "Must fail for self-approval specifically");
      await record(page, { role: "supervisor", name: "Identity merges — self-approval is refused", detail: `The supervisor who raised the request cannot approve it: the server answered ${refused.status()}. Proving the refusal matters more than proving the happy path.` });
    });

    await withRole("dev.supervisor2", async (page) => {
      await open(page, "/supervisor/merges");
      await click(page, "2. Approve");
      await field(page, "Merge log ID", mergeLogId);
      const approved = await responseTo(page, "POST", `/emergency/patients/promotions/${mergeLogId}/approve`, () => click(page, "Confirm and assign UHID"));
      assert.equal(approved.status, "approved");
      await record(page, { role: "supervisor", name: "Identity merges — a second supervisor approves", detail: `A different supervisor approved the promotion and the chart was assigned a permanent UHID. The temporary identity \`${thid}\` is now a real record.` });
    });

    await withRole("dev.supervisor", async (page) => {
      await open(page, "/supervisor/merges");
      await click(page, "3. Unmerge");
      await field(page, "Merge log ID", mergeLogId);
      await field(page, "Unmerge reason", "Synthetic verification rollback.");
      // The screen asks for confirmation before an unmerge; accept it.
      page.on("dialog", (dialog) => void dialog.accept());
      const unmerged = await responseTo(page, "POST", `/emergency/patients/promotions/${mergeLogId}/unmerge`, () => click(page, "Unmerge promotion"));
      assert.equal(unmerged.status, "unmerged");
      await record(page, { role: "supervisor", name: "Identity merges — unmerge a wrong promotion", detail: "Reversed the promotion, returning the chart to its temporary identity. Unmerge is performed by someone other than the approver." });
      console.log(`PASS emergency_and_merge: ${thid} promoted, approved by a second supervisor, then unmerged`);
    });
  },
  /**
   * The auditor's two jobs: narrowing the trail, and taking a copy of it.
   *
   * Filters are asserted by the row count MOVING, not by the screen not
   * erroring — a filter wired to nothing renders exactly like one that
   * matched everything, which is how a dead Resource filter survived here
   * before.
   */
  async auditor() {
    await withRole("dev.auditor", async (page) => {
      await open(page, "/audit-viewer");
      // MUI renders each row as a button carrying this test id; there is no
      // table to count.
      await page.waitForFunction(() => document.querySelectorAll('[data-testid="audit-log-row"]').length > 0, { timeout: 30_000 });
      const unfiltered = await page.$$eval('[data-testid="audit-log-row"]', (rows) => rows.length);
      assert.ok(unfiltered > 0, "The audit trail must show rows before any filter is applied");
      await record(page, { role: "auditor", name: "Audit trail — the default view", detail: `${unfiltered} row(s) render before any filter is touched. This view used to open empty until a filter was applied.` });

      // The Resource filter is a MUI select: a combobox that opens a listbox,
      // not a native <select>. Options come from GET /audit/resource-types, so
      // every one of them has rows behind it.
      const chosen = await page.evaluate(() => {
        const combos = [...document.querySelectorAll('[role="combobox"]')];
        const resource = combos.find((c) => c.closest(".MuiFormControl-root")?.textContent?.includes("Resource"));
        resource?.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
        resource?.click();
        return Boolean(resource);
      });
      assert.ok(chosen, "The Resource filter must be present for an auditor");
      await page.waitForSelector('[role="listbox"] [role="option"]', { timeout: 30_000 });
      const resourceValue = await page.evaluate(() => {
        const options = [...document.querySelectorAll('[role="listbox"] [role="option"]')]
          .filter((o) => (o.getAttribute("data-value") ?? o.textContent?.trim()) !== "all");
        const option = options[0];
        option?.click();
        return option?.textContent?.trim() ?? null;
      });
      assert.ok(resourceValue, "The Resource filter must offer a type this facility has rows for");

      // Wait for a settled result, not merely a changed one: the list empties
      // for a moment while it refetches, and counting during that window reads
      // zero and looks exactly like a filter that matches nothing.
      await page.waitForFunction((before) => {
        const rows = document.querySelectorAll('[data-testid="audit-log-row"]').length;
        return rows > 0 && rows !== before;
      }, { timeout: 30_000 }, unfiltered);
      const filtered = await page.$$eval('[data-testid="audit-log-row"]', (rows) => rows.length);
      assert.notEqual(filtered, unfiltered, `Filtering by ${resourceValue} left the row count unchanged — the filter is wired to nothing`);
      assert.ok(filtered > 0, `The Resource filter offered ${resourceValue}, which matches nothing — the options must come from the data`);
      await record(page, { role: "auditor", name: "Audit trail — filtering narrows the result", detail: `Filtering to \`${resourceValue}\` moved the row count from ${unfiltered} to ${filtered}, and still matched rows. A filter wired to nothing renders identically to one that matched everything, so the count has to move and stay non-zero.` });
      console.log(`PASS auditor: ${unfiltered} -> ${filtered} rows under resource "${resourceValue}"`);
    });
  },
  /**
   * The patient portal. The assertion that matters is not that it renders —
   * it is that it renders THIS patient and refuses everyone else's chart.
   */
  async patient_portal() {
    await withRole("dev.patient", async (page, { token }) => {
      const forbidden = [];
      page.on("response", (r) => {
        const path = new URL(r.url()).pathname;
        if (path.startsWith("/api/v1/") && r.status() >= 400) forbidden.push(`${r.status()} ${path}`);
      });
      const portalPaths = ["/binding", "/me/abha", "/me/consents", "/me/access-history"];
      const reads = portalPaths.map((suffix) => responseTo(page, "GET", `/patient-portal${suffix}`, async () => {}));
      const [binding, abha] = await Promise.all([...reads, open(page, "/patient-portal")]);
      assert.ok(binding.patient_id, "The portal must have a verified patient binding");
      assert.equal(abha.patient_id, binding.patient_id, "Portal reads must agree on the bound patient");
      await text(page, "Portal identity verified by");
      assert.deepEqual(forbidden, [], "The portal must load a patient's own record without a single refusal");
      await record(page, { role: "patient", name: "My health record — own chart and access history", detail: "The portal loaded this patient's own record, ABHA link status and data-access history with no failing call. Every read here is scoped to the signed-in patient by the server." });

      // Containment, checked at the API with this patient's own bearer token.
      // A hidden sidebar entry stops a confused user and does nothing about a
      // token and curl, so the redirect is the weaker assertion.
      const bearer = token();
      assert.ok(bearer, "no bearer token captured from the Keycloak exchange");
      const denials = await page.evaluate(async (jwt, routes) => {
        const out = [];
        for (const [method, path, body] of routes) {
          const response = await fetch(path, {
            method,
            headers: { Authorization: `Bearer ${jwt}`, "Content-Type": "application/json" },
            body: body ? JSON.stringify(body) : undefined,
          });
          out.push([`${method} ${path}`, response.status]);
        }
        return out;
      }, bearer, [
        ["GET", "/api/v1/audit/logs", null],
        ["GET", "/api/v1/queue/worklist", null],
        ["POST", "/api/v1/patients/search", { full_name: "a" }],
      ]);
      for (const [route, status] of denials) {
        assert.equal(status, 403, `A patient must be refused ${route}, got ${status}`);
      }
      await record(page, { role: "patient", name: "Patient portal — staff routes are refused at the API", detail: `With this patient's own token, ${denials.map(([r]) => `\`${r}\``).join(", ")} all answered 403. The sidebar hiding them is containment, not authorisation.` });
      console.log(`PASS patient_portal: own record loaded; ${denials.length} staff route(s) refused 403`);
    });
  },
  /**
   * Admission, and the ward round that depends on it.
   *
   * This is the chain that left the nurse with no action-level coverage: every
   * nursing screen — vitals, fluid balance, movement, the eMAR — is keyed on an
   * *admitted* patient, and being admitted needs an IPD visit plus a ward and a
   * vacant bed. Reception creates the visit, the ward admits into a bed, and
   * only then does the nurse have someone to chart.
   */
  async ipd_and_nursing() {
    let visitId = null;
    let patientName = null;

    await withRole("dev.receptionist", async (page) => {
      await open(page, "/receptionist/registration");
      await click(page, "No existing record — register new");
      patientName = `Ward Test ${randomUUID().replace(/[0-9-]/g, "a")}`;
      await field(page, "Full name *", patientName);
      await field(page, "Sex *", "female");
      await page.evaluate(() => {
        const input = [...document.querySelectorAll('#main-content input[type="date"]')].at(-1);
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, "1990-01-01");
        input.dispatchEvent(new Event("input", { bubbles: true }));
      });
      await responseTo(page, "POST", "/patients", () => click(page, "Register patient"), 201);
      await field(page, "Visit type", "ipd");
      const visit = await responseTo(page, "POST", "/visits", () => click(page, "Create visit"), 201);
      visitId = visit.id;
      assert.equal(visit.visit_type, "ipd");
      await record(page, { role: "receptionist", name: "Registration — IPD visit for admission", detail: `Created the IPD visit the ward admits against. No counter token is issued for an admission.` });
    });

    let bedNumber = null;
    let createdAdmissionId = null;
    await withRole("dev.nurse", async (page) => {
      await open(page, "/ipd");
      await click(page, "Admit");
      await setById(page, "field-visit_id", visitId);

      await page.waitForFunction(() => (document.getElementById("field-ward_id")?.options?.length ?? 0) > 0, { timeout: 30_000 });
      const wardId = await page.evaluate(() => {
        const select = document.getElementById("field-ward_id");
        return [...(select?.options ?? [])].find((o) => o.value)?.value ?? null;
      });
      assert.ok(wardId, "A ward must exist before anyone can be admitted");
      await setById(page, "field-ward_id", wardId);

      // Only vacant beds in the chosen ward are offered, so the first card is
      // a real free bed rather than a guess.
      await page.waitForFunction(() => [...document.querySelectorAll('#main-content [role="button"]')].some((b) => b.querySelector("h3")), { timeout: 30_000 });
      bedNumber = await page.evaluate(() => {
        const card = [...document.querySelectorAll('#main-content [role="button"]')].find((b) => b.querySelector("h3"));
        card.click();
        return card.querySelector("h3").textContent.trim();
      });
      assert.ok(bedNumber, "A vacant bed is required");

      const admittedAt = localDateTime();
      await setById(page, "field-admitted_at", admittedAt);
      await setById(page, "field-reason", "Synthetic browser verification. No clinical content.");
      const admission = await responseTo(page, "POST", "/admissions", () => click(page, "Admit Patient"), 201);
      createdAdmissionId = admission.id;
      assert.equal(admission.visit_id, visitId);
      assert.equal(admission.status, "admitted");
      await record(page, { role: "nurse", name: `IPD — admit to a bed`, detail: `Admitted the patient into bed \`${bedNumber}\`, chosen from the vacant beds in that ward. Every nursing screen below is keyed on this admission.` });
    });

    await withRole("dev.nurse", async (page) => {
      await open(page, "/nurse/ward-dashboard");
      await page.waitForFunction(() => (document.getElementById("ward")?.options?.length ?? 0) > 0, { timeout: 30_000 });
      const wardId = await page.evaluate(() => {
        const select = document.getElementById("ward");
        return [...(select?.options ?? [])].find((o) => o.value)?.value ?? null;
      });
      await setById(page, "ward", wardId);

      await page.waitForFunction((wanted) => [...document.querySelectorAll('#main-content [role="button"]')]
        .some((b) => b.querySelector("h3")?.textContent?.trim() === wanted), { timeout: 30_000 }, bedNumber);
      await page.evaluate((wanted) => {
        [...document.querySelectorAll('#main-content [role="button"]')]
          .find((b) => b.querySelector("h3")?.textContent?.trim() === wanted).click();
      }, bedNumber);

      // The bed must resolve to the patient just admitted — "Occupants come
      // directly from the active admission attached to each bed".
      await text(page, patientName);
      await record(page, { role: "nurse", name: "Ward dashboard — the bed resolves to its occupant", detail: `Selecting bed \`${bedNumber}\` opens the live chart for the patient admitted into it.` });

      await click(page, "Record vitals");
      await setById(page, "field-temp_c", "37.1");
      await setById(page, "field-pulse_bpm", "78");
      await setById(page, "field-resp_rate", "16");
      await setById(page, "field-spo2_pct", "98");
      await setById(page, "field-bp_systolic", "118");
      await setById(page, "field-bp_diastolic", "76");
      // Weight and height are deliberately left blank. Every optional numeric
      // field used to reach zod as NaN, so a nurse could not save a pulse
      // without also weighing the patient; leaving them empty is the
      // regression check. The decimal temperature above is the other one — a
      // native step of 1 silently blocked the submit entirely.
      await responseTo(page, "POST", "/nursing/vitals", () => click(page, "Save Vitals"), 201);

      // Read it back on the timeline rather than trusting the 201: the submit
      // hook swallows failures into console.error and returns false.
      await page.waitForFunction(() => document.querySelector("#main-content")?.textContent?.includes("37.1"), { timeout: 30_000 });
      // Shift handover: the table shipped in 0050 with no writer, so the ward
      // could not record the moment responsibility for a patient transferred.
      await click(page, "Record handover");
      await page.waitForSelector("#field-situation", { timeout: 30_000 });
      await setById(page, "field-shift", "night");
      const receiver = await page.evaluate(() => {
        const select = document.getElementById("field-handed_over_to");
        const option = [...(select?.options ?? [])].find((o) => o.value && o.value !== "__manual__");
        return option ? { value: option.value, label: option.textContent.trim() } : null;
      });
      assert.ok(receiver, "A colleague must be offerable as the receiving nurse");
      await setById(page, "field-handed_over_to", receiver.value);
      await setById(page, "field-situation", "Post-operative day one, stable.");
      await setById(page, "field-background", "Admitted for elective procedure.");
      await setById(page, "field-assessment", "Vitals within range, pain controlled.");
      await setById(page, "field-recommendation", "Continue observations four-hourly.");
      await responseTo(page, "POST", "/nursing/handover-notes", () => click(page, "Complete Handover"), 201);
      // Read it back on the board, by the receiver's NAME — the list used to
      // print a truncated uuid because no endpoint resolved one.
      await text(page, receiver.label.split(" · ")[0]);
      await record(page, { role: "nurse", name: "Ward dashboard — record a shift handover", detail: `Recorded an SBAR handover to \`${receiver.label}\` and read it back on the ward board by name. The table has existed since migration 0050 with no model, service or route behind it, so this could not be done at all before.` });

      await record(page, { role: "nurse", name: "Ward dashboard — record vitals", detail: "Charted a set of observations against the admission and confirmed they appear on the patient's vitals timeline, not merely that the POST returned 201." });
    });

    // Discharge closes the loop and returns the bed. Without it this workflow
    // consumes one bed per run and stops working once the ward fills — and the
    // discharge path would stay untested, which is half the admission story.
    await withRole("dev.nurse", async (page) => {
      await open(page, "/ipd");
      await click(page, "Discharge");
      assert.ok(createdAdmissionId, "Only discharge the synthetic admission created by this run");
      await page.waitForFunction((wanted) => [...document.querySelectorAll("#main-content option")]
        .some((o) => o.value === wanted), { timeout: 30_000 }, createdAdmissionId);
      const admissionId = await page.evaluate((wanted) => {
        const select = [...document.querySelectorAll("#main-content select")]
          .find((sel) => [...sel.options].some((o) => o.value === wanted));
        const option = [...select.options].find((o) => o.value === wanted);
        const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set;
        setter.call(select, option.value);
        select.dispatchEvent(new Event("input", { bubbles: true }));
        select.dispatchEvent(new Event("change", { bubbles: true }));
        return option.value;
      }, createdAdmissionId);
      assert.equal(admissionId, createdAdmissionId, "Never select a different admission by a reusable bed label");

      await setById(page, "field-discharge_type", "discharged");
      await setById(page, "field-discharged_at", localDateTime());
      await setById(page, "field-discharge_summary", "Synthetic browser verification. No clinical content.");
      await click(page, "Preview Discharge");
      await responseTo(page, "POST", `/admissions/${admissionId}/discharge`, () => click(page, "Confirm Discharge"));
      await record(page, { role: "nurse", name: "IPD — discharge and free the bed", detail: `Discharged the admission through the two-step preview/confirm flow, returning bed \`${bedNumber}\` to the vacant pool.` });
      console.log(`PASS ipd_and_nursing: admitted to ${bedNumber}, charted vitals, discharged`);
    });
  },
  /**
   * The core clinical path, end to end, across three roles.
   *
   *   HOD rosters a doctor -> reception opens that queue -> reception registers
   *   a patient and issues a token -> the doctor consults and completes it ->
   *   the token leaves the waiting list.
   *
   * Every screen involved already passed a load check, and every one of these
   * steps was still unproven: a dashboard that reads cleanly tells you nothing
   * about whether the day's work can actually be done on it. The last
   * assertion is a regression on the reported defect where a consultation was
   * marked Completed and the patient stayed Waiting in the doctor's queue
   * forever.
   *
   * Adaptive on purpose: it rosters and opens only what is missing, so it is
   * safe to run repeatedly against the same development stack.
   */
  async opd_journey() {
    const DOCTOR = "Dev Doctor";

    // 1. A queue for our doctor has to exist. Roster them if reception has no
    //    option to open one.
    let queueOpen = false;
    await withRole("dev.receptionist", async (page) => {
      await open(page, "/receptionist/queue");
      // Settle on a definite answer rather than a timing guess: either this
      // doctor's queue card is on screen, or the page says there are none.
      await page.waitForFunction((wanted) => {
        const main = document.querySelector("#main-content");
        return [...document.querySelectorAll("#main-content button")].some((b) => b.textContent?.includes(wanted))
          || Boolean(main?.textContent?.includes("No open queues today"));
      }, { timeout: 30_000 }, DOCTOR);
      queueOpen = await page.evaluate((wanted) => [...document.querySelectorAll("#main-content button")].some((b) => b.textContent?.includes(wanted)), DOCTOR);
    });

    // The roster step runs every time, not only when a queue is missing: it
    // tolerates 409 (already rostered), and skipping it on a re-run would
    // leave the department head with no action-level evidence at all.
    {
      await withRole("dev.hod", async (page) => {
        await open(page, "/hod");
        await page.waitForFunction((wanted) => {
          const select = [...document.querySelectorAll("#main-content label")]
            .find((l) => l.querySelector("span")?.textContent?.trim() === "Staff member")
            ?.querySelector("select");
          return [...(select?.options ?? [])].some((o) => o.textContent?.includes(wanted));
        }, { timeout: 30_000 }, DOCTOR);
        const staffId = await page.evaluate((wanted) => {
          const select = [...document.querySelectorAll("#main-content label")]
            .find((l) => l.querySelector("span")?.textContent?.trim() === "Staff member")
            ?.querySelector("select");
          return [...(select?.options ?? [])].find((o) => o.textContent?.includes(wanted))?.value ?? null;
        }, DOCTOR);
        assert.ok(staffId, `${DOCTOR} must be rosterable by their HOD`);
        await field(page, "Staff member", staffId);
        // 409 means this doctor is already on today's roster, which is the
        // state this step exists to reach. Re-running the journey against the
        // same stack must not fail on work a previous run already did.
        const responsePromise = page.waitForResponse((r) => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/v1/queue/rosters", { timeout: 30_000 });
        await click(page, "Add to roster");
        const response = await responsePromise;
        assert.ok([201, 409].includes(response.status()), `POST /queue/rosters returned ${response.status()}`);
        if (response.status() === 201) {
          assert.equal((await response.json()).data?.staff_user_id ?? (await response.json()).staff_user_id, staffId);
        }
        await record(page, { role: "hod", name: "Department roster — add a doctor", detail: `Rostered ${DOCTOR} for today. Reception cannot open an OPD queue until a department head has done this, so this is the first step of the clinical day.` });
      });

    }

    if (!queueOpen) {
      await withRole("dev.receptionist", async (page) => {
        await open(page, "/receptionist/queue");
        await click(page, "Open queue");
        await page.waitForFunction((wanted) => {
          const select = [...document.querySelectorAll("#main-content label")]
            .find((l) => l.querySelector("span")?.textContent?.trim() === "Rostered clinic")
            ?.querySelector("select");
          return [...(select?.options ?? [])].some((o) => o.textContent?.includes(wanted));
        }, { timeout: 30_000 }, DOCTOR);
        const optionId = await page.evaluate((wanted) => {
          const select = [...document.querySelectorAll("#main-content label")]
            .find((l) => l.querySelector("span")?.textContent?.trim() === "Rostered clinic")
            ?.querySelector("select");
          return [...(select?.options ?? [])].find((o) => o.textContent?.includes(wanted))?.value ?? null;
        }, DOCTOR);
        assert.ok(optionId, "The roster entry just created must be offerable to reception");
        await field(page, "Rostered clinic", optionId);
        await responseTo(page, "POST", "/queue/queues", () => click(page, "Open"), 201);
        await text(page, DOCTOR);
        await record(page, { role: "receptionist", name: "Queue — open today's OPD clinic", detail: `Opened today's queue for ${DOCTOR} from the HOD-approved roster.` });
      });
    }

    // 2. Register a walk-in and issue them a real token.
    let tokenDisplay = null;
    let patientName = null;
    let patientId = null;
    const diagnosticItems = {};
    await withRole("dev.receptionist", async (page) => {
      await open(page, "/receptionist/registration");
      // The desk searches for an existing record before creating one; the new
      // patient form only appears once that search has been declined.
      await click(page, "No existing record — register new");
      patientName = `Journey Test ${randomUUID().replace(/[0-9-]/g, "a")}`;
      await field(page, "Full name *", patientName);
      await field(page, "Sex *", "female");
      await page.evaluate(() => {
        const input = [...document.querySelectorAll('#main-content input[type="date"]')].at(-1);
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, "1990-01-01");
        input.dispatchEvent(new Event("input", { bubbles: true }));
      });
      patientId = (await responseTo(page, "POST", "/patients", () => click(page, "Register patient"), 201)).id;
      await field(page, "Visit type", "opd");
      // The doctor list is fetched after mount, so the select does not exist
      // yet at this point in the render.
      await page.waitForFunction((wanted) => {
        const select = [...document.querySelectorAll("#main-content label")]
          .find((l) => l.querySelector("span")?.textContent?.trim() === "Doctor")
          ?.querySelector("select");
        return [...(select?.options ?? [])].some((o) => o.textContent?.includes(wanted));
      }, { timeout: 30_000 }, DOCTOR);
      const queueId = await page.evaluate((wanted) => {
        const select = [...document.querySelectorAll("#main-content label")]
          .find((l) => l.querySelector("span")?.textContent?.trim() === "Doctor")
          ?.querySelector("select");
        return [...(select?.options ?? [])].find((o) => o.textContent?.includes(wanted))?.value ?? null;
      }, DOCTOR);
      assert.ok(queueId, `An open queue for ${DOCTOR} must be offered at the desk`);
      await field(page, "Doctor", queueId);
      const token = await responseTo(page, "POST", "/queue/tokens", () => click(page, "Create visit and issue token"), 201);
      tokenDisplay = token.token_display;
      assert.ok(tokenDisplay, "An OPD visit must produce a token number");
      await text(page, tokenDisplay);
      await record(page, { role: "receptionist", name: "Registration — OPD visit and token", detail: `Registered a walk-in and issued token \`${tokenDisplay}\`. Unlike the non-OPD types, an outpatient visit does take a counter token.` });
    });

    // 3. Consent. The clinical record is gated on an active `clinical_review`
    //    consent; without it the doctor gets "Record locked" and the only way
    //    in is a two-hour break-glass override. That gate is correct, so the
    //    journey records the consent the desk would take at registration.
    await withRole("dev.receptionist", async (page) => {
      await open(page, "/consent");
      await page.waitForSelector("#main-content form input", { timeout: 30_000 });
      await page.type("#main-content form input", patientName);
      await page.evaluate(() => {
        const date = document.querySelector("#main-content form input[type='date']");
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(date, "1990-01-01");
        date.dispatchEvent(new Event("input", { bubbles: true }));
        date.dispatchEvent(new Event("change", { bubbles: true }));
      });
      await click(page, "Search");
      // Name search is deliberately fuzzy, so every earlier synthetic patient
      // matches too. Pick the row for this exact patient rather than the only
      // button, which is not unique here.
      await page.waitForFunction((wanted) => [...document.querySelectorAll("#main-content li,#main-content tr")]
        .some((row) => row.textContent?.includes(wanted) && row.querySelector("button")), { timeout: 30_000 }, patientName);
      await page.evaluate((wanted) => {
        const row = [...document.querySelectorAll("#main-content li,#main-content tr")]
          .find((r) => r.textContent?.includes(wanted) && r.querySelector("button"));
        const button = [...row.querySelectorAll("button")].find((b) => b.textContent?.trim() === "View consents");
        if (!button) throw new Error("No View consents button on the matched row");
        button.click();
      }, patientName);

      await page.waitForFunction(() => {
        const select = [...document.querySelectorAll("#main-content label")]
          .find((l) => l.querySelector("span")?.textContent?.trim() === "Purpose *")
          ?.querySelector("select");
        return [...(select?.options ?? [])].some((o) => /clinical review/i.test(o.textContent ?? ""));
      }, { timeout: 30_000 });
      const purposeId = await page.evaluate(() => {
        const select = [...document.querySelectorAll("#main-content label")]
          .find((l) => l.querySelector("span")?.textContent?.trim() === "Purpose *")
          ?.querySelector("select");
        return [...(select?.options ?? [])].find((o) => /clinical review/i.test(o.textContent ?? ""))?.value ?? null;
      });
      assert.ok(purposeId, "A clinical_review consent purpose must be configured");
      await field(page, "Purpose *", purposeId);
      const consent = await responseTo(page, "POST", `/consent/patients/${patientId}/records`, () => click(page, "Record consent"), 201);
      assert.equal(consent.status, "granted");
      await record(page, { role: "receptionist", name: "Consent — record clinical review", detail: `Recorded a granted \`clinical_review\` consent for the patient. Without it the doctor's record view stays locked and the only way in is an audited two-hour break-glass override.` });
    });

    // 4. The doctor consults that patient and closes the encounter.
    await withRole("dev.doctor", async (page) => {
      await open(page, "/doctor/dashboard");
      // Keyed on the patient, not the token number. `token_display` restarts
      // per department per day, so several rows can read GENMED-002 and the
      // first match is not necessarily this one.
      await page.waitForFunction((wanted) => [...document.querySelectorAll("#main-content tbody tr")].some((r) => r.textContent?.includes(wanted)), { timeout: 30_000 }, patientName);
      const waitingBefore = await page.evaluate((wanted) => {
        const row = [...document.querySelectorAll("#main-content tbody tr")].find((r) => r.textContent?.includes(wanted));
        return row?.textContent?.includes("Waiting") ?? false;
      }, patientName);
      assert.ok(waitingBefore, `${patientName} (${tokenDisplay}) must reach the doctor's queue as Waiting`);
      await record(page, { role: "doctor", name: "Doctor queue — the walk-in arrives", detail: `Token \`${tokenDisplay}\` issued at reception appears in the doctor's live queue as Waiting.` });

      await page.evaluate((wanted) => {
        [...document.querySelectorAll("#main-content tbody tr")].find((r) => r.textContent?.includes(wanted))?.click();
      }, patientName);

      // "Start consultation" is a link, not a button.
      await page.waitForFunction(() => [...document.querySelectorAll("#main-content a")].some((a) => a.textContent?.trim() === "Start consultation"), { timeout: 30_000 });
      await Promise.all([
        page.waitForNavigation({ waitUntil: "domcontentloaded", timeout: 60_000 }),
        page.evaluate(() => {
          [...document.querySelectorAll("#main-content a")].find((a) => a.textContent?.trim() === "Start consultation").click();
        }),
      ]);
      assert.equal(new URL(page.url()).pathname, "/doctor/consultation");
      assert.ok(new URL(page.url()).searchParams.get("token"), "The consultation must carry the queue token");

      await page.waitForSelector('#main-content textarea', { timeout: 30_000 });
      await page.evaluate(() => {
        const input = document.querySelector('#main-content textarea');
        Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(input, "Synthetic browser verification. No clinical content.");
        input.dispatchEvent(new Event("input", { bubbles: true }));
      });
      const encounter = await responseTo(page, "POST", "/encounters", () => click(page, "Save encounter"), 201);
      assert.ok(encounter.id, "Saving must return a real encounter");
      await record(page, { role: "doctor", name: "Consultation — save the encounter", detail: "Recorded a chief complaint and saved the encounter, which is what unlocks vitals, diagnoses, orders and prescriptions on this screen." });

      for (const kind of ["lab", "radiology"]) {
        await click(page, "+ Add order");
        if (kind !== "lab") await muiSelect(page, "Order type", kind);
        const label = `Synthetic ${kind} verification ${randomUUID().slice(0, 8)}`;
        await muiField(page, kind === "lab" ? "Test name" : "Study name", label);
        const department = kind === "lab" ? "pathology" : "radiology";
        const item = await responseTo(page, "POST", `/${department}/order-items`, () => click(page, "Add order"), 201);
        assert.ok(item.id && item.accession_number, "The department item must exist, not just an order header");
        diagnosticItems[kind] = item;
        await text(page, item.accession_number);
        await record(page, { role: "doctor", name: `Consultation — place ${kind} order`, detail: `Created the order header and its department item, then displayed accession ${item.accession_number}. Synthetic test order only.` });
      }

      await responseTo(page, "PATCH", `/encounters/${encounter.id}`, () => click(page, "Complete consultation"));
      await text(page, "Completed");
      await record(page, { role: "doctor", name: "Consultation — complete", detail: "Closed the encounter. The queue token must close with it." });

      // The reported defect: the consultation said Completed and the patient
      // stayed Waiting in the queue for the rest of the day.
      const worklist = await responseTo(page, "GET", "/queue/worklist", () => open(page, "/doctor/dashboard"));
      assert.ok(Array.isArray(worklist.items), "Queue refresh must return its worklist before checking completion");
      const refreshedToken = worklist.items.find((row) => row.patient_id === patientId);
      assert.ok(!refreshedToken || refreshedToken.status === "completed", "The refreshed server worklist must not leave this visit waiting or in service");
      await page.waitForFunction((wanted) => {
        const main = document.querySelector("#main-content");
        if (!main || main.textContent.includes("Loading") || main.querySelector('[role="alert"]')) return false;
        const row = [...document.querySelectorAll("#main-content tbody tr")].find((r) => r.textContent?.includes(wanted));
        return !row || !row.textContent?.includes("Waiting");
      }, { timeout: 30_000 }, patientName);
      await record(page, { role: "doctor", name: "Doctor queue — the token closes with the consultation", detail: `After completion, \`${tokenDisplay}\` is no longer Waiting. This is the regression check for the defect where a completed consultation left its patient in the queue indefinitely.` });
      console.log(`PASS opd_journey: ${tokenDisplay} rostered, queued, consulted and closed`);
    });

    const lab = diagnosticItems.lab;
    await withRole("dev.labtech", async (page) => {
      await open(page, "/lab");
      await openAccession(page, lab.accession_number);
      await field(page, "Sample barcode", `E2E-${randomUUID().slice(0, 8)}`);
      await transitionResponse(page, "PUT", `/pathology/order-items/${lab.id}/sample-collection`, () => click(page, "Confirm sample collection"), "in_progress");
      await text(page, "Sample collected.");
      await record(page, { role: "lab_tech", name: "Lab — collect ordered sample", detail: "Collected the synthetic doctor's order with a unique barcode; the worklist moved to in progress." });
      await field(page, "Result data (JSON object)", '{"synthetic_verification": true}');
      await transitionResponse(page, "POST", `/pathology/order-items/${lab.id}/results`, () => click(page, "Save preliminary result"), "preliminary", 201);
      await text(page, "Preliminary result saved.");
      const rejected = page.waitForResponse((r) => r.request().method() === "PUT" && new URL(r.url()).pathname === `/api/v1/pathology/order-items/${lab.id}/results/verify`);
      await click(page, "Verify and release");
      assert.equal((await rejected).status(), 403, "The author must not release their own result");
      await text(page, "Maker–checker blocked this action.");
      await page.reload({ waitUntil: "domcontentloaded" });
      await openAccession(page, lab.accession_number);
      await text(page, "Version 1 · preliminary");
      await text(page, "synthetic_verification");
      await record(page, { role: "lab_tech", name: "Lab — result persists and self-verification is refused", detail: "Saved a synthetic preliminary result, received 403 on self-verification, then reloaded its unchanged preliminary history. Independent release still needs a second lab-tech identity." });
    });

    const scan = diagnosticItems.radiology;
    await withRole("dev.radiology", async (page) => {
      await open(page, "/radiology");
      await openAccession(page, scan.accession_number);
      await field(page, "Scheduled at", localDateTime(new Date(Date.now() + 60 * 60_000)));
      await field(page, "Machine", "E2E-SYNTHETIC");
      await transitionResponse(page, "PUT", `/radiology/order-items/${scan.id}/schedule`, () => click(page, "Schedule"), "scheduled");
      await text(page, "Mark scan complete");
      await field(page, "New slot", localDateTime(new Date(Date.now() + 120 * 60_000)));
      await field(page, "Reason", "Synthetic rescheduling verification");
      await transitionResponse(page, "PUT", `/radiology/order-items/${scan.id}/reschedule`, () => click(page, "Save new slot"), "scheduled");
      await transitionResponse(page, "PUT", `/radiology/order-items/${scan.id}/scan-complete`, () => click(page, "Mark scan complete"), "scanned");
      await text(page, "scanned");
      assert.equal(await page.$$eval("button", (buttons) => buttons.filter((b) => ["Save preliminary", "Sign off as final"].includes(b.textContent?.trim())).length), 0, "A technician must not be offered doctor-only report actions");
      await record(page, { role: "radiology_tech", name: "Radiology — schedule, reschedule, complete scan", detail: "Booked and moved a synthetic scan with a reason, marked it scanned, and verified doctor-only reporting controls are not offered to the technician." });
    });

    await withRole("dev.doctor", async (page) => {
      await open(page, "/lab");
      await openAccession(page, lab.accession_number);
      await text(page, "Read-only result view.");
      assert.equal(await page.$$eval("button", (buttons) => buttons.filter((b) => ["Confirm sample collection", "Save preliminary result", "Verify and release"].includes(b.textContent?.trim())).length), 0, "A doctor must not be offered lab-technician mutations");
      await open(page, "/radiology");
      await openAccession(page, scan.accession_number);
      await field(page, "Findings", "Synthetic browser verification. Not a clinical report.");
      await field(page, "Impression", "Synthetic verification only.");
      await field(page, "PACS study UID", "2.25.123456789");
      await transitionResponse(page, "POST", `/radiology/order-items/${scan.id}/reports`, () => click(page, "Save preliminary"), "preliminary", 201);
      await text(page, "Sign off as final");
      await transitionResponse(page, "PUT", `/radiology/order-items/${scan.id}/reports/sign-off`, () => click(page, "Sign off as final"), "final");
      await page.reload({ waitUntil: "domcontentloaded" });
      await openAccession(page, scan.accession_number);
      await text(page, "v2 · final");
      await text(page, "v1 · preliminary");
      await text(page, "DiagnosticReport");
      await record(page, { role: "doctor", name: "Radiology — draft, sign off, reload report history", detail: "The doctor drafted and finalized the synthetic scan, then reloaded both report versions and the DiagnosticReport bundle." });
    });
  },
  /**
   * The OPD corridor TV. It is the only unauthenticated screen in the product,
   * it renders outside the app chrome, and no role's sidebar links to it — so
   * the role sweep cannot reach it and it had no browser coverage at all.
   *
   * The assertion that matters is not "it rendered": it is that a browser with
   * no session reaches the board, and that the stream it opens carries no
   * credential. A display that only worked while a staff cookie happened to be
   * present would pass a casual look and fail on the wall.
   */
  async queue_display() {
    let departmentId;
    await withRole("dev.admin", async (page) => {
      const departments = await responseTo(page, "GET", "/departments", () => open(page, "/admin/departments"));
      const items = departments.items ?? departments;
      assert.ok(Array.isArray(items) && items.length > 0, "Seeded department required");
      departmentId = items[0].id;
    });

    // A context created fresh here shares no cookies or storage with the admin
    // sign-in above; this is genuinely anonymous.
    const context = await browser.createBrowserContext();
    const page = await context.newPage();
    const streamRequests = [];
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (url.pathname.startsWith("/api/v1/queue/display/")) {
        streamRequests.push({ path: url.pathname, authorization: request.headers().authorization ?? null });
      }
    });
    try {
      await page.goto(`${baseUrl}/queue-display?department=${departmentId}`, { waitUntil: "domcontentloaded", timeout: 60_000 });
      assert.equal(new URL(page.url()).pathname, "/queue-display", "A corridor screen must not be bounced to /login");
      await page.waitForFunction(() => document.body.textContent?.includes("Live"), { timeout: 30_000 });
      assert.equal(streamRequests.length, 1, "Expected exactly one display stream subscription");
      assert.equal(streamRequests[0].authorization, null, "The wall display stream must not require a credential");
      await record(page, { role: "public", name: "Queue display — corridor wall screen", detail: `Opened \`/queue-display\` in a browser with no session, reached the board without a login redirect, and the department stream went \`Live\` over a request carrying no Authorization header.` });
      console.log("PASS queue_display: anonymous browser reached a live, credential-free board");
    } finally {
      await context.close();
    }
  },
  async non_opd() {
    await withRole("dev.receptionist", async (page) => {
      for (const kind of ["ipd", "day_care", "emergency", "teleconsult"]) {
        await open(page, "/receptionist/registration");
        await click(page, "No existing record — register new");
        const name = `Browser Test ${randomUUID().replace(/[0-9-]/g, "a")}`;
        await field(page, "Full name *", name);
        await field(page, "Sex *", "female");
        await page.evaluate(() => {
          const inputs = [...document.querySelectorAll('#main-content input[type="date"]')];
          const input = inputs.at(-1);
          Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, "1990-01-01");
          input.dispatchEvent(new Event("input", { bubbles: true }));
        });
        const patient = await responseTo(page, "POST", "/patients", () => click(page, "Register patient"), 201);
        await field(page, "Visit type", kind);
        let tokens = 0;
        const observe = (r) => { if (r.method() === "POST" && new URL(r.url()).pathname === "/api/v1/queue/tokens") tokens++; };
        page.on("request", observe);
        const visit = await responseTo(page, "POST", "/visits", () => click(page, "Create visit"), 201);
        assert.equal(visit.patient_id, patient.id);
        assert.equal(visit.visit_type, kind);
        await text(page, "Visit created");
        assert.equal(tokens, 0, "Non-OPD visit must not issue an OPD token");
        assert.equal(await page.$$eval('select', (nodes) => nodes.filter((n) => n.closest("label")?.textContent.includes("Doctor")).length), 0);
        page.off("request", observe);
        await record(page, { role: "receptionist", name: `Registration — ${kind} visit`, detail: `Registered a patient and created a \`${kind}\` visit. The visit persisted against that patient id, no OPD queue token was issued, and no doctor selector was offered — the OPD pipeline no longer runs for every visit type.` });
        console.log(`PASS receptionist: ${kind} visit persisted without an OPD token`);
      }
    });
  },
};

let failures = 0;
try {
  if (requested) assert.ok(workflows[requested], `Unknown workflow ${requested}`);
  for (const [name, run] of Object.entries(workflows)) {
    if (requested && requested !== name) continue;
    currentWorkflow = name;
    try {
      await run();
      workflowResults.push({ name, passed: true, failures: [] });
      console.log(`PASS ${name}`);
    } catch (error) {
      failures++;
      workflowResults.push({ name, passed: false, failures: [error.message] });
      console.error(`FAIL ${name}: ${error.message}`);
    }
  }
} finally {
  await browser.close();
}

if (evidenceDir) {
  await mkdir(evidenceDir, { recursive: true });
  await writeFile(
    path.join(evidenceDir, "workflows.json"),
    `${JSON.stringify({
      capturedAt: new Date().toISOString(), baseUrl, runId,
      completed: true, fullRun: !requested, recoveryAllowed: allowRecovery,
      plannedWorkflows: requested ? [requested] : Object.keys(workflows),
      results: workflowResults, steps: evidence,
      warnings,
    }, null, 2)}\n`,
  );
  console.log(`Evidence: ${evidence.length} workflow step(s) captured in ${evidenceDir}`);
}

process.exitCode = failures ? 1 : 0;
