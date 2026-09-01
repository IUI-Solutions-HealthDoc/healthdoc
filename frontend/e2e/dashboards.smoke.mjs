/**
 * Per-dashboard smoke: every screen loads AND every call it makes succeeds.
 *
 * WHY "IT RENDERED" IS NOT THE ASSERTION
 *
 * Every defect this project actually shipped rendered perfectly:
 *
 *   - app/radiology was a title-only shell for weeks and looked finished from
 *     the route list;
 *   - procurement had create and approve endpoints with no list endpoint, so
 *     the approval queue was empty rather than broken;
 *   - the HOD dashboard's eight endpoints had no page at all;
 *   - `orders.fulfilment_mode` was written by nothing, so every order claimed
 *     the hospital would fulfil it in-house.
 *
 * A "does the page render" test passes on all four. So this fails the build if
 * ANY request to /api/v1 returns 4xx or 5xx while a dashboard is loading, and
 * separately if the page paints its own error state. Those are the two ways a
 * screen tells you it is broken, and both are invisible to a screenshot.
 *
 * WHAT IT DELIBERATELY DOES NOT DO
 *
 * Drive mutating workflows. Raising an indent and approving it needs seeded
 * data per role and a run long enough that CI time becomes a real cost. The
 * consent screen does perform a read-only patient selection so its lazy API
 * wiring is covered. This is the cheap gate that catches "wired to nothing";
 * the journey tests in backend/tests/integration cover the state changes.
 *
 * A 404 from a LIST endpoint is a failure here. A 404 on a detail route for a
 * record that does not exist in the seed would not be — so no dashboard below
 * is given an id to fetch. Every path is a landing screen.
 */
import process from "node:process";

import puppeteer from "puppeteer";

const baseUrl = process.env.E2E_BASE_URL ?? "https://localhost";
const requestedRole = process.env.E2E_ROLE;
const executablePath = process.env.PUPPETEER_EXECUTABLE_PATH ?? undefined;

/**
 * Dashboards per role, as the sidebar offers them.
 *
 * `expectCalls` is the floor, not the ceiling: a screen that makes ZERO API
 * calls is the shell failure this file exists to catch, so a dashboard listed
 * here must prove it talked to the backend at all.
 *
 * `expectedResponses` names an exact method, path and status whose response is
 * a legitimate answer the screen renders. Each entry needs a reason. A path-
 * only or blanket 404 exception would excuse precisely the missing-endpoint
 * failure this file exists to catch.
 */
const ROLE_DASHBOARDS = [
  {
    name: "receptionist",
    username: "dev.receptionist",
    landingPath: "/receptionist/registration",
    dashboards: [
      { path: "/receptionist/registration", expectCalls: false },
      { path: "/receptionist/patient-search", expectCalls: false },
      { path: "/receptionist/queue", expectCalls: true },
      { path: "/billing", expectCalls: true },
      {
        path: "/consent",
        expectCalls: true,
        exercise: "patientConsent",
        requiredRequests: [
          { method: "POST", path: "/api/v1/patients/search" },
          { method: "GET", pathPrefix: "/api/v1/consent/patients/", pathSuffix: "/records" },
        ],
      },
    ],
  },
  {
    name: "doctor",
    username: "dev.doctor",
    landingPath: "/doctor/dashboard",
    dashboards: [
      { path: "/doctor/dashboard", expectCalls: true },
      {
        path: "/doctor/consultation",
        expectCalls: false,
        expectedText: "Open a patient from the live OPD queue",
      },
      { path: "/doctor/orders", expectCalls: true },
      { path: "/doctor/prescriptions", expectCalls: true },
      { path: "/doctor/results", expectCalls: true },
      { path: "/doctor/pharmacy-approvals", expectCalls: true },
      { path: "/lab", expectCalls: true },
      { path: "/radiology", expectCalls: true },
      { path: "/ipd", expectCalls: true },
      {
        path: "/consent",
        expectCalls: true,
        exercise: "patientConsent",
        requiredRequests: [
          { method: "POST", path: "/api/v1/patients/search" },
          { method: "GET", pathPrefix: "/api/v1/consent/patients/", pathSuffix: "/records" },
        ],
      },
    ],
  },
  {
    name: "nurse",
    username: "dev.nurse",
    landingPath: "/nurse/ward-dashboard",
    dashboards: [
      { path: "/nurse/ward-dashboard", expectCalls: true },
      { path: "/nurse/emar", expectCalls: true },
      { path: "/ipd", expectCalls: true },
      {
        path: "/consent",
        expectCalls: true,
        exercise: "patientConsent",
        requiredRequests: [
          { method: "POST", path: "/api/v1/patients/search" },
          { method: "GET", pathPrefix: "/api/v1/consent/patients/", pathSuffix: "/records" },
        ],
      },
    ],
  },
  {
    name: "lab_tech",
    username: "dev.labtech",
    landingPath: "/lab",
    dashboards: [
      { path: "/lab", expectCalls: true },
      // Maintenance is explicitly writable by lab technicians; testing only
      // the admin path would leave that advertised role unproved.
      { path: "/admin/maintenance", expectCalls: true },
    ],
  },
  {
    name: "radiology_tech",
    username: "dev.radiology",
    landingPath: "/radiology",
    dashboards: [
      { path: "/radiology", expectCalls: true },
      { path: "/admin/maintenance", expectCalls: true },
    ],
  },
  {
    name: "pharmacist",
    username: "dev.pharmacist",
    landingPath: "/pharmacy/prescription-queue",
    dashboards: [
      { path: "/pharmacy/prescription-queue", expectCalls: true },
      { path: "/pharmacy/dispense", expectCalls: true },
      // Loads reorder alerts and the expiry tracker on mount; the five stock
      // tabs are separate components and are not exercised by a page load.
      { path: "/inventory", expectCalls: true },
    ],
  },
  {
    name: "emergency",
    username: "dev.emergency",
    landingPath: "/emergency",
    dashboards: [
      {
        path: "/emergency",
        expectCalls: false,
        expectedText: "Emergency registration",
      },
    ],
  },
  {
    name: "supervisor",
    username: "dev.supervisor",
    landingPath: "/supervisor/merges",
    dashboards: [
      {
        path: "/supervisor/merges",
        // This workspace is intentionally mutation-driven: it cannot call an
        // identity API until a supervisor supplies a patient or merge-log ID.
        expectCalls: false,
        expectedText: "Identity merges",
        exercise: "supervisorMergeTabs",
      },
      { path: "/reports", expectCalls: true },
    ],
  },
  {
    name: "hod",
    username: "dev.hod",
    landingPath: "/hod",
    dashboards: [
      // Dashboard summary reads plus the roster manager. Before this screen
      // existed the role had no landing page and these endpoints were unreachable.
      {
        path: "/hod",
        expectCalls: true,
        // These three reads prove the roster manager is mounted against live
        // staff, room and roster APIs. The create itself remains a deliberate
        // manual workflow — dashboard smoke tests do not mutate shared data.
        requiredRequests: [
          { method: "GET", path: "/api/v1/queue/roster-candidates" },
          { method: "GET", path: "/api/v1/departments/rooms" },
          { method: "GET", path: "/api/v1/queue/rosters" },
        ],
      },
      // HOD-only indent approval lives here. Reachable only because
      // ROLES.HOD gained the /inventory prefix — without it the one action
      // only a department head can perform had no route.
      { path: "/inventory", expectCalls: true },
    ],
  },
  {
    name: "admin",
    username: "dev.admin",
    landingPath: "/admin",
    dashboards: [
      { path: "/admin", expectCalls: false },
      { path: "/admin/users", expectCalls: true },
      { path: "/admin/departments", expectCalls: true },
      { path: "/admin/permissions", expectCalls: true },
      { path: "/admin/account-requests", expectCalls: true },
      // Search-driven: the API is intentionally not called until an admin
      // supplies a patient identifier. A zero-call mount is correct here.
      { path: "/admin/abdm-sync", expectCalls: false },
      { path: "/audit-viewer", expectCalls: true },
      {
        path: "/admin/data-protection",
        expectCalls: true,
        // A facility that has never appointed a DPO genuinely has none, and
        // the screen says so in a warning rather than an error. The other
        // three reads on this page must still succeed.
        expectedResponses: [
          {
            method: "GET",
            path: "/api/v1/dpdp/dpo",
            status: 404,
            reason: "No DPO has been appointed at the seeded facility",
          },
        ],
      },
      { path: "/admin/maintenance", expectCalls: true },
      { path: "/reports", expectCalls: true },
      { path: "/billing", expectCalls: true },
    ],
  },
  {
    name: "auditor",
    username: "dev.auditor",
    landingPath: "/audit-viewer",
    dashboards: [
      { path: "/audit-viewer", expectCalls: true },
      {
        path: "/admin/data-protection",
        expectCalls: true,
        // Same legitimate absence as the admin view. The auditor must not need
        // admin-only GET /users merely to load this register.
        expectedResponses: [
          {
            method: "GET",
            path: "/api/v1/dpdp/dpo",
            status: 404,
            reason: "No DPO has been appointed at the seeded facility",
          },
        ],
      },
      { path: "/reports", expectCalls: true },
    ],
  },
  {
    name: "patient",
    username: "dev.patient",
    landingPath: "/patient-portal",
    dashboards: [{ path: "/patient-portal", expectCalls: true }],
  },
  {
    name: "superadmin",
    username: "dev.superadmin",
    landingPath: "/superadmin",
    dashboards: [
      {
        path: "/superadmin",
        expectCalls: true,
        expectedText: "Registered facilities",
      },
    ],
  },
];

const selectedRoles = requestedRole
  ? ROLE_DASHBOARDS.filter((role) => role.name === requestedRole)
  : ROLE_DASHBOARDS;

if (selectedRoles.length === 0) {
  console.error(`E2E_ROLE="${requestedRole}" matches no role in this file`);
  process.exit(1);
}

async function signIn(page, role) {
  await page.goto(`${baseUrl}/login`, { waitUntil: "domcontentloaded", timeout: 30_000 });

  // SSR paints before AuthProvider finishes silent SSO. Waiting for an enabled
  // button keeps this from becoming an inert pre-hydration click — the same
  // trap staff-auth.smoke.mjs documents.
  await page.waitForSelector("button:not([disabled])", { timeout: 30_000 });
  const clicked = await page.evaluate(() => {
    const button = [...document.querySelectorAll("button")].find(
      (candidate) =>
        !candidate.disabled && candidate.textContent?.includes("Sign in with Keycloak"),
    );
    button?.click();
    return Boolean(button);
  });
  if (!clicked) throw new Error("Keycloak sign-in button was not rendered");

  await page.waitForSelector("#username", { timeout: 30_000 });
  await page.type("#username", role.username);
  await page.type("#password", "devpass");
  await Promise.all([
    page.waitForNavigation({ waitUntil: "domcontentloaded", timeout: 30_000 }),
    page.click("#kc-login"),
  ]);
  await page.waitForFunction(
    (expected) => window.location.pathname === expected,
    { timeout: 60_000 },
    role.landingPath,
  );
  // The pathname changes before silent SSO has restored the in-memory token.
  // #main-content exists only after MainLayout knows this role is authenticated.
  try {
    await page.waitForSelector("#main-content", { timeout: 60_000 });
  } catch (_error) {
    // In the development stack, compiling many role routes back-to-back can
    // restart Next after Keycloak has already completed the redirect. Reload
    // the authenticated landing route once; a real auth/role defect still
    // fails because the required content and sidebar remain mandatory.
    console.warn(
      `[${role.name}] landing page did not hydrate after login; reloading once`,
    );
    await page.reload({ waitUntil: "domcontentloaded", timeout: 60_000 });
    await page.waitForFunction(
      (expected) => window.location.pathname === expected,
      { timeout: 60_000 },
      role.landingPath,
    );
    await page.waitForSelector("#main-content", { timeout: 60_000 });
  }
  await page.waitForSelector("#workspace-sidebar", { timeout: 30_000 });

  const visibleMenuPaths = await page.evaluate(() =>
    [...document.querySelectorAll("#workspace-sidebar a[href]")]
      .map((link) => new URL(link.href).pathname)
      .sort(),
  );
  const expectedMenuPaths = role.dashboards.map((dashboard) => dashboard.path).sort();
  if (JSON.stringify(visibleMenuPaths) !== JSON.stringify(expectedMenuPaths)) {
    throw new Error(
      `role menu mismatch; expected ${expectedMenuPaths.join(", ")}; ` +
        `rendered ${visibleMenuPaths.join(", ")}`,
    );
  }
}

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function exercisePatientConsent(page) {
  await page.waitForSelector("#main-content form input", { timeout: 30_000 });
  await page.type("#main-content form input", "Dev Patient");
  // Name search is intentionally paired with DOB: a fuzzy name alone is not
  // enough identity evidence to attach consent or a clinical visit.
  await page.evaluate(() => {
    const date = document.querySelector("#main-content form input[type='date']");
    if (date) {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )?.set;
      setter?.call(date, "1990-01-01");
      date.dispatchEvent(new Event("input", { bubbles: true }));
      date.dispatchEvent(new Event("change", { bubbles: true }));
    }
  });
  const searchClicked = await page.evaluate(() => {
    const button = [...document.querySelectorAll("#main-content form button")].find(
      (candidate) => candidate.textContent?.trim() === "Search",
    );
    button?.click();
    return Boolean(button);
  });
  if (!searchClicked) throw new Error("patient search button was not rendered");

  await page.waitForFunction(
    () =>
      [...document.querySelectorAll("#main-content button")].some(
        (candidate) => candidate.textContent?.trim() === "View consents",
      ),
    { timeout: 30_000 },
  );
  await page.evaluate(() => {
    const button = [...document.querySelectorAll("#main-content button")].find(
      (candidate) => candidate.textContent?.trim() === "View consents",
    );
    button?.click();
  });
  await page.waitForFunction(
    () =>
      document.querySelector("#main-content")?.textContent?.includes("Dev Patient") &&
      document.querySelector("#main-content")?.textContent?.includes("change patient"),
    { timeout: 30_000 },
  );
}

async function exerciseSupervisorMergeTabs(page) {
  const steps = [["2. Approve", "Approve pending promotion"], ["3. Unmerge", "Unmerge approved promotion"]];
  for (const [label, heading] of steps) {
    await page.evaluate((wanted) => {
      const button = [...document.querySelectorAll("#main-content button")].find(
        (candidate) => candidate.textContent?.trim() === wanted,
      );
      button?.click();
    }, label);
    await page.waitForFunction(
      (wanted) => document.querySelector("#main-content h2")?.textContent === wanted,
      { timeout: 10_000 },
      heading,
    );
  }
}

async function runConfiguredExercise(page, dashboard) {
  if (!dashboard.exercise) return;
  if (dashboard.exercise === "patientConsent") {
    await exercisePatientConsent(page);
    return;
  }
  if (dashboard.exercise === "supervisorMergeTabs") {
    await exerciseSupervisorMergeTabs(page);
    return;
  }
  throw new Error(`unknown dashboard exercise ${dashboard.exercise}`);
}

function isExpectedResponse(dashboard, request, url, status) {
  return (dashboard.expectedResponses ?? []).find(
    (expected) =>
      expected.method === request.method() &&
      expected.path === url.pathname &&
      expected.status === status,
  );
}

async function waitForApiSettlement(observed, expectCalls) {
  const firstCallDeadline = Date.now() + 15_000;
  while (expectCalls && observed.started === 0 && Date.now() < firstCallDeadline) {
    await delay(100);
  }

  // Wait until every started request has either produced headers or failed,
  // and the count has stayed still for a beat. Unlike networkidle2 this works
  // with HMR, SSE and other intentionally long-lived browser connections.
  const completionDeadline = Date.now() + 30_000;
  let lastStarted = observed.started;
  let stableSince = Date.now();
  while (Date.now() < completionDeadline) {
    if (observed.started !== lastStarted) {
      lastStarted = observed.started;
      stableSince = Date.now();
    }
    if (
      observed.responded + observed.requestFailed >= observed.started &&
      Date.now() - stableSince >= 750
    ) {
      break;
    }
    await delay(100);
  }
}

async function openDashboard(page, role, dashboard) {
  let lastError;
  for (let attempt = 1; attempt <= 2; attempt += 1) {
    try {
      await page.goto(`${baseUrl}${dashboard.path}`, {
        waitUntil: "domcontentloaded",
        timeout: 60_000,
      });
      await page.waitForFunction(
        (expected) => window.location.pathname === expected,
        { timeout: 60_000 },
        dashboard.path,
      );
      await page.waitForSelector("#main-content", { timeout: 60_000 });
      await page.waitForFunction(
        () => (document.querySelector("#main-content")?.textContent?.trim().length ?? 0) > 0,
        { timeout: 60_000 },
      );
      return;
    } catch (error) {
      lastError = error;
      if (attempt === 2) break;
      console.warn(
        `[${role.name}] ${dashboard.path} — navigation did not settle; retrying once ` +
          `(the Next.js development server can restart after compiling many routes)`,
      );
      await delay(1_500);
    }
  }
  throw lastError;
}

async function exerciseDashboard(context, role, dashboard) {
  const page = await context.newPage();
  const failures = [];
  const expectedSeen = new Set();
  const observed = {
    started: 0,
    responded: 0,
    requestFailed: 0,
    bad: [],
    missingBearer: [],
    requests: [],
  };
  let active = true;

  page.on("request", (request) => {
    if (!active) return;
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/v1")) return;
    observed.started += 1;
    observed.requests.push({ method: request.method(), path: url.pathname });
    if (!request.headers().authorization?.startsWith("Bearer ")) {
      observed.missingBearer.push(`${request.method()} ${url.pathname}`);
    }
  });
  page.on("response", (response) => {
    if (!active) return;
    const request = response.request();
    const url = new URL(response.url());
    if (!url.pathname.startsWith("/api/v1")) return;
    observed.responded += 1;
    const expected = isExpectedResponse(dashboard, request, url, response.status());
    if (expected) expectedSeen.add(`${expected.method} ${expected.path} ${expected.status}`);
    if (response.status() >= 400 && !expected) {
      observed.bad.push(`${response.status()} ${request.method()} ${url.pathname}`);
    }
  });
  page.on("requestfailed", (request) => {
    if (!active) return;
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/v1")) return;
    observed.requestFailed += 1;
    observed.bad.push(
      `request failed ${request.method()} ${url.pathname}: ${request.failure()?.errorText ?? "unknown"}`,
    );
  });
  page.on("pageerror", (error) => {
    if (active) failures.push(`${dashboard.path}: uncaught ${error.message}`);
  });

  try {
    await openDashboard(page, role, dashboard);

    const landed = await page.evaluate(() => window.location.pathname);
    if (landed !== dashboard.path) {
      failures.push(`${dashboard.path}: role ${role.name} was redirected to ${landed}`);
      return { failures, observed, offeredNavigation: [] };
    }

    if (dashboard.expectedText) {
      const hasExpectedText = await page.$eval(
        "#main-content",
        (node, expected) => node.textContent?.includes(expected),
        dashboard.expectedText,
      );
      if (!hasExpectedText) {
        failures.push(`${dashboard.path}: did not render ${JSON.stringify(dashboard.expectedText)}`);
      }
    }

    await runConfiguredExercise(page, dashboard);
    await waitForApiSettlement(observed, dashboard.expectCalls);

    const alerts = await page.$$eval('[role="alert"]', (nodes) =>
      nodes.map((node) => node.textContent?.trim()).filter(Boolean),
    );
    if (alerts.length > 0) {
      failures.push(`${dashboard.path}: rendered an error — ${alerts.join(" | ")}`);
    }
    if (observed.bad.length > 0) {
      failures.push(`${dashboard.path}: ${observed.bad.join(", ")}`);
    }
    if (observed.missingBearer.length > 0) {
      failures.push(
        `${dashboard.path}: API request(s) had no Bearer token — ${observed.missingBearer.join(", ")}`,
      );
    }
    if (dashboard.expectCalls && observed.started === 0) {
      failures.push(
        `${dashboard.path}: made NO /api/v1 calls — a screen wired to nothing ` +
          "renders exactly like a working one",
      );
    }
    if (observed.responded + observed.requestFailed < observed.started) {
      failures.push(
        `${dashboard.path}: ${observed.started - observed.responded - observed.requestFailed} ` +
          "API request(s) never produced a response",
      );
    }
    for (const expected of dashboard.expectedResponses ?? []) {
      const key = `${expected.method} ${expected.path} ${expected.status}`;
      if (!expectedSeen.has(key)) {
        failures.push(
          `${dashboard.path}: did not observe expected ${key} (${expected.reason})`,
        );
      }
    }
    for (const required of dashboard.requiredRequests ?? []) {
      const seen = observed.requests.some(
        (request) =>
          request.method === required.method &&
          (required.path ? request.path === required.path : true) &&
          (required.pathPrefix ? request.path.startsWith(required.pathPrefix) : true) &&
          (required.pathSuffix ? request.path.endsWith(required.pathSuffix) : true),
      );
      if (!seen) {
        failures.push(
          `${dashboard.path}: did not make required ${required.method} ` +
            `${required.path ?? `${required.pathPrefix ?? ""}*${required.pathSuffix ?? ""}`}`,
        );
      }
    }

    if (!dashboard.expectCalls) {
      const interactiveCount = await page.$$eval(
        "#main-content a[href], #main-content button, #main-content input, #main-content select, #main-content textarea",
        (nodes) => nodes.length,
      );
      if (interactiveCount === 0 && !dashboard.expectedText) {
        failures.push(`${dashboard.path}: rendered no API data and no interactive control`);
      }
    }

    const offeredNavigation = await page.$$eval("#workspace-sidebar a[href]", (links) =>
      [...new Set(links.map((link) => new URL(link.href).pathname))].sort(),
    );
    console.log(
      `[${role.name}] ${dashboard.path} — ${observed.responded}/${observed.started} API ` +
        `response(s), ${observed.bad.length} failed`,
    );
    return { failures, observed, offeredNavigation };
  } finally {
    active = false;
    await page.close();
  }
}

async function exerciseRole(browser, role) {
  const context = await browser.createBrowserContext();
  const failures = [];
  try {
    const authPage = await context.newPage();
    try {
      await signIn(authPage, role);
    } finally {
      await authPage.close();
    }

    let offeredNavigation = null;
    for (const dashboard of role.dashboards) {
      try {
        const result = await exerciseDashboard(context, role, dashboard);
        failures.push(...result.failures);
        offeredNavigation ??= result.offeredNavigation;
      } catch (error) {
        failures.push(
          `${dashboard.path}: smoke could not finish — ${error instanceof Error ? error.message : error}`,
        );
      }
    }

    const testedPaths = new Set(role.dashboards.map((dashboard) => dashboard.path));
    const uncoveredNavigation = (offeredNavigation ?? []).filter((path) => !testedPaths.has(path));
    if (uncoveredNavigation.length > 0) {
      failures.push(`sidebar screen(s) have no smoke: ${uncoveredNavigation.join(", ")}`);
    }
    if (role.unsupportedReason) {
      console.log(`[${role.name}] explicit unsupported gap — ${role.unsupportedReason}`);
    }
  } catch (error) {
    failures.push(`login failed — ${error instanceof Error ? error.message : error}`);
  } finally {
    await context.close();
  }

  return failures;
}

const browser = await puppeteer.launch({
  headless: "new",
  executablePath,
  // The stack serves TLS with a self-signed certificate in dev and CI.
  args: ["--no-sandbox", "--ignore-certificate-errors"],
});

const allFailures = [];
try {
  const preflight = await browser.newPage();
  try {
    const response = await preflight.goto(`${baseUrl}/api/v1/health`, {
      waitUntil: "domcontentloaded",
      timeout: 15_000,
    });
    if (!response || response.status() !== 200) {
      throw new Error(`dashboard smoke preflight returned ${response?.status() ?? "no response"}`);
    }
  } finally {
    await preflight.close();
  }

  for (const role of selectedRoles) {
    console.log(`\n=== ${role.name} ===`);
    const failures = await exerciseRole(browser, role);
    allFailures.push(...failures.map((f) => `[${role.name}] ${f}`));
  }
} finally {
  await browser.close();
}

if (allFailures.length > 0) {
  console.error(`\n${allFailures.length} dashboard failure(s):`);
  for (const failure of allFailures) console.error(`  ✗ ${failure}`);
  process.exit(1);
}

console.log("\nEvery available dashboard loaded, rendered, and completed its bearer API calls.");
