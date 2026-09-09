/** Shared controls for local acceptance. Tokens stay in memory, never evidence. */
import assert from "node:assert/strict";

export const baseUrl = process.env.E2E_BASE_URL ?? "https://localhost";
assert(["localhost", "127.0.0.1", "[::1]"].includes(new URL(baseUrl).hostname), "Local acceptance only");

export async function click(page, label) {
  await page.waitForFunction((wanted) => [...document.querySelectorAll("button")].some((b) => b.textContent?.trim() === wanted && !b.disabled), { timeout: 30_000 }, label);
  await page.evaluate((wanted) => [...document.querySelectorAll("button")].find((b) => b.textContent?.trim() === wanted && !b.disabled).click(), label);
}

export async function field(page, label, value) {
  await page.evaluate((wanted, next) => {
    const lab = [...document.querySelectorAll("label")].find((l) => l.textContent.trim() === wanted || l.querySelector("span")?.textContent.trim() === wanted);
    const input = lab?.querySelector("input,select,textarea") ?? document.getElementById(lab?.htmlFor);
    if (!input) throw new Error(`Missing field ${wanted}`);
    const proto = input instanceof HTMLSelectElement ? HTMLSelectElement.prototype : input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(input, next);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }, label, value);
}

export async function open(page, pathname) {
  await page.goto(`${baseUrl}${pathname}`, { waitUntil: "domcontentloaded", timeout: 60_000 });
  await page.waitForSelector("#main-content", { timeout: 60_000 });
  assert.equal(new URL(page.url()).pathname, pathname);
}

export async function login(browser, username) {
  const context = await browser.createBrowserContext();
  const loginPage = await context.newPage();
  const failures = [];
  loginPage.on("pageerror", (error) => failures.push(error.message));
  loginPage.on("response", (response) => {
    if (response.status() >= 400) failures.push(`${response.status()} ${new URL(response.url()).pathname}`);
  });
  let token;
  const capture = async (response) => {
    if (!new URL(response.url()).pathname.endsWith("/protocol/openid-connect/token")) return;
    try { token = (await response.json()).access_token ?? token; } catch { /* Navigation can abort a body. */ }
  };
  loginPage.on("response", capture);
  try {
    await loginPage.goto(`${baseUrl}/login`, { waitUntil: "domcontentloaded", timeout: 60_000 });
    await click(loginPage, "Sign in with Keycloak");
    await loginPage.waitForSelector("#username");
    await loginPage.type("#username", username);
    await loginPage.type("#password", "devpass");
    await loginPage.click("#kc-login");
    await loginPage.waitForFunction(() => !["/", "/login"].includes(location.pathname) && !location.pathname.startsWith("/auth/"), { timeout: 60_000 });
    await loginPage.waitForSelector("#main-content", { timeout: 60_000 });
    assert.ok(token, "Real Keycloak token exchange required");
    const page = await context.newPage();
    page.on("response", capture);
    const api = async (method, pathname, body, expected = 200, headers = {}) => {
      const result = await page.evaluate(async (args) => {
        const response = await fetch(`/api/v1${args.pathname}`, {
          signal: AbortSignal.timeout(30_000),
          method: args.method,
          headers: { Authorization: `Bearer ${args.token}`, "Content-Type": "application/json", ...(args.method !== "GET" ? { "Idempotency-Key": crypto.randomUUID() } : {}), ...args.headers },
          ...(args.body === undefined ? {} : { body: JSON.stringify(args.body) }),
        });
        return { status: response.status, body: response.status === 204 ? null : await response.json() };
      }, { token, method, pathname, body, headers });
      assert.equal(result.status, expected, `${method} ${pathname}: ${JSON.stringify(result.body?.error ?? {})}`);
      return result.body?.data ?? result.body;
    };
    return { context, page, api };
  } catch (error) {
    const controls = await loginPage.$$eval("button", (buttons) => buttons.map((b) => ({ text: b.textContent?.trim(), disabled: b.disabled }))).catch(() => []);
    console.error("Login diagnostics", { path: new URL(loginPage.url()).pathname, controls, failures });
    await context.close();
    throw error;
  }
}
