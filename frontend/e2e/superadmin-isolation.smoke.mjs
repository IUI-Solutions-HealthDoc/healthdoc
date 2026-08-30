/**
 * #464 — the superadmin workspace is isolated, proved in a real browser.
 *
 * The issue asks for a journey that proves "the real superadmin login, bearer
 * authentication, permitted operations, and denied facility/clinical routes".
 * The last of those is the part that matters, and it is checked at BOTH layers
 * on purpose:
 *
 *   API   a real bearer token against facility/clinical endpoints must come
 *         back 403. This is the one that counts.
 *   UI    navigating to a facility workspace must redirect away.
 *
 * Checking only the UI would be the mistake CLAUDE.md already records costing
 * this project real time: "UI containment is not authorization. Six endpoints
 * returned 200 to a role the frontend redirected away." A hidden menu stops a
 * confused operator and does nothing about a token and curl, so the redirect is
 * the weaker assertion and is treated as such here.
 *
 * The denied list is not invented — each entry is a route whose require_roles
 * excludes superadmin, read off the mounted app:
 *   /patients/search   admin, doctor, nurse, receptionist
 *   /queue/worklist    doctor
 *   /audit/logs        admin, auditor
 *   /billing/invoices  admin, receptionist, supervisor
 *   /users             admin
 */
import { existsSync } from "node:fs";
import process from "node:process";

import puppeteer from "puppeteer";

const baseUrl = process.env.E2E_BASE_URL ?? "https://localhost";
const executablePath =
  process.env.PUPPETEER_EXECUTABLE_PATH ??
  [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
  ].find(existsSync);

/** Permitted: the workspace's own data. */
const PERMITTED = [{ method: "GET", path: "/platform/facilities", expect: 200 }];

/** Denied: facility and clinical data, none of which grants superadmin. */
const DENIED = [
  { method: "POST", path: "/patients/search", body: { full_name: "probe" } },
  { method: "GET", path: "/queue/worklist" },
  { method: "GET", path: "/audit/logs" },
  { method: "GET", path: "/billing/invoices" },
  { method: "GET", path: "/users" },
];

/** Facility workspaces the client guard must keep a platform operator out of. */
const FORBIDDEN_ROUTES = ["/admin", "/doctor/dashboard", "/receptionist/registration"];

const failures = [];
const settle = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const browser = await puppeteer.launch({
  headless: "new",
  executablePath,
  args: ["--ignore-certificate-errors", "--no-sandbox"],
  acceptInsecureCerts: true,
});
const page = await browser.newPage();

let accessToken = null;
page.on("response", (response) => {
  const url = new URL(response.url());
  if (
    response.request().method() === "POST" &&
    url.pathname.endsWith("/protocol/openid-connect/token")
  ) {
    void response
      .json()
      .then((body) => {
        if (body.access_token) accessToken = body.access_token;
      })
      .catch(() => undefined);
  }
});

try {
  // ---- real Keycloak login, no shortcuts -----------------------------------
  await page.goto(`${baseUrl}/login`, { waitUntil: "networkidle2", timeout: 45_000 });
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
  await page.type("#username", "dev.superadmin");
  await page.type("#password", "devpass");
  await Promise.all([
    page.waitForNavigation({ waitUntil: "domcontentloaded", timeout: 30_000 }),
    page.click("#kc-login"),
  ]);

  await page.waitForFunction(() => window.location.pathname !== "/login", { timeout: 60_000 });
  await settle(4000);

  const landing = await page.evaluate(() => window.location.pathname);
  if (landing !== "/superadmin") {
    failures.push(`landed on ${landing}, expected /superadmin`);
  }

  for (let i = 0; i < 50 && !accessToken; i += 1) await settle(200);
  if (!accessToken) throw new Error("no bearer token captured from the Keycloak exchange");

  const claims = JSON.parse(Buffer.from(accessToken.split(".")[1], "base64url").toString());
  const realmRoles = claims.realm_access?.roles ?? [];
  if (!realmRoles.includes("superadmin")) {
    failures.push(`token does not carry the superadmin role: ${realmRoles.join(", ")}`);
  }
  console.log(`signed in as dev.superadmin -> ${landing}`);
  console.log(`realm roles: ${[...realmRoles].sort().join(", ")}\n`);

  // ---- the API layer, which is the one that counts -------------------------
  const probe = async ({ method, path, body }) =>
    page.evaluate(
      async (method, path, body, token) => {
        const headers = { Authorization: `Bearer ${token}` };
        const init = { method, headers };
        if (body) {
          headers["Content-Type"] = "application/json";
          headers["Idempotency-Key"] = crypto.randomUUID();
          init.body = JSON.stringify(body);
        }
        const response = await fetch(`/api/v1${path}`, init);
        return response.status;
      },
      method,
      path,
      body ?? null,
      accessToken,
    );

  for (const permitted of PERMITTED) {
    const status = await probe(permitted);
    const ok = status === permitted.expect;
    console.log(`  ${ok ? "PASS" : "FAIL"} permitted  ${permitted.method} ${permitted.path} -> ${status}`);
    if (!ok) failures.push(`${permitted.path} returned ${status}, expected ${permitted.expect}`);
  }

  for (const denied of DENIED) {
    const status = await probe(denied);
    // 403 specifically. A 404 would mean the route moved and this stopped
    // testing anything; a 200 is the finding this whole file exists to catch.
    const ok = status === 403;
    console.log(`  ${ok ? "PASS" : "FAIL"} denied     ${denied.method} ${denied.path} -> ${status}`);
    if (!ok) failures.push(`${denied.path} returned ${status}, expected 403`);
  }

  // ---- the UI layer, weaker and checked second -----------------------------
  console.log("");
  for (const route of FORBIDDEN_ROUTES) {
    await page.goto(`${baseUrl}${route}`, { waitUntil: "networkidle2", timeout: 45_000 });
    await settle(3500);
    const settled = await page.evaluate(() => window.location.pathname);
    const ok = settled !== route;
    console.log(`  ${ok ? "PASS" : "FAIL"} ui         ${route} -> settled ${settled}`);
    if (!ok) failures.push(`${route} rendered for superadmin instead of redirecting`);
  }
} finally {
  await browser.close();
}

console.log("");
if (failures.length > 0) {
  console.error(`FAIL — superadmin isolation broken in ${failures.length} place(s):`);
  for (const failure of failures) console.error(`  - ${failure}`);
  process.exit(1);
}
console.log("PASS — superadmin: permitted platform call 200, every facility/clinical route 403, every facility workspace redirected.");
