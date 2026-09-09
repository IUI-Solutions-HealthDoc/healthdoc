import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";
import { z } from "zod";

function load(file, dependencies) {
  const code = ts.transpileModule(readFileSync(new URL(file, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const exports = {};
  new Function("require", "exports", code)((name) => {
    assert.ok(name in dependencies, `Unexpected dependency ${name}`);
    return dependencies[name];
  }, exports);
  return exports;
}
const rows = [{ id: "old", scheme_code: null, is_active: false, unit_price: "71.23" },
  { id: "scheme", scheme_code: "TEST", is_active: true, unit_price: "0.00" }];

test("tariff catalogue consumes the unwrapped array and asks the server for retired history", async () => {
  const calls = [];
  const client = load("../src/features/billing/api/chargeMaster.ts", { "@/lib/api": {
    api: async (...args) => { calls.push(args); return rows; }, newIdempotencyKey: () => "key",
  } });
  assert.deepEqual(await client.listChargeMaster({ active_only: false }), rows);
  assert.equal(calls[0][0], "/billing/charge-master?active_only=false");
  assert.equal(await client.getChargeMaster("old"), rows[0]);
});

test("successful bodyless 204 is not treated as an API failure", async (t) => {
  t.mock.method(globalThis, "fetch", async () => new Response(null, { status: 204 }));
  const client = load("../src/lib/api.ts", {
    "./api-error-policy.mjs": { userFacingApiError: () => "Failure" },
    "./session-policy.mjs": {}, "./auth": {},
  });
  assert.equal(await client.api("/billing/charge-master/id/deactivate", { method: "POST", idempotencyKey: "key" }), undefined);
});

test("tariff filtering uses exact server code and complete-array scheme selection", async () => {
  const calls = [];
  const client = load("../src/features/billing/api/chargeMaster.ts", { "@/lib/api": {
    api: async (...args) => { calls.push(args); return rows; },
  } });
  assert.deepEqual(await client.listChargeMaster({ scheme_code: "TEST", charge_code: "A&B" }), [rows[1]]);
  assert.equal(calls[0][0], "/billing/charge-master?active_only=true&charge_code=A%26B");
});

test("catalogue read failures and malformed shapes do not become empty success", async () => {
  const failure = new Error("Forbidden");
  let response = { items: rows };
  const client = load("../src/features/billing/api/chargeMaster.ts", { "@/lib/api": {
    api: async () => { if (response === failure) throw failure; return response; },
  } });
  await assert.rejects(client.listChargeMaster(), /invalid response/);
  response = failure;
  await assert.rejects(client.listChargeMaster(), /Forbidden/);
});

test("create and retire preserve exact decimal strings, optional scheme and action keys", async () => {
  const calls = [];
  const client = load("../src/features/billing/api/chargeMaster.ts", { "@/lib/api": {
    api: async (...args) => { calls.push(args); },
  } });
  const payload = { charge_code: "TEST", description: "Synthetic only", charge_category: "lab",
    unit_price: "9999999999.99", scheme_code: null, effective_from: "2026-09-09" };
  await client.createTariff(payload, "create-key");
  await client.deactivateTariff("old", "retire-key");
  assert.equal(calls[0][0], "/billing/charge-master");
  assert.deepEqual(JSON.parse(calls[0][1].body), payload);
  assert.equal(calls[0][1].idempotencyKey, "create-key");
  assert.equal(calls[1][0], "/billing/charge-master/old/deactivate");
  assert.equal(calls[1][1].idempotencyKey, "retire-key");
  assert.ok(calls.every(([, options]) => options.method === "POST"));
});

test("only 204 bypasses envelope parsing; refusals and invalid responses still reject", async (t) => {
  let response = new Response(null, { status: 403 });
  t.mock.method(globalThis, "fetch", async () => response);
  const client = load("../src/lib/api.ts", {
    "./api-error-policy.mjs": { userFacingApiError: () => "Failure" },
    "./session-policy.mjs": {}, "./auth": {},
  });
  for (const status of [403, 409, 500, 200]) {
    response = new Response(null, { status });
    await assert.rejects(client.api("/test"), (error) => error.code === status);
  }
});

const schema = load("../src/features/billing/lib/tariff-form.ts", { zod: { z } }).tariffFormSchema;
const valid = { charge_code: "TEST", description: "Synthetic only", charge_category: "lab", unit_price: "71.23", effective_from: "2026-09-09", scheme_code: "" };
test("tariff form normalizes exact money and general scheme without floating point", () => {
  for (const [input, expected] of [["0", "0.00"], ["00071.2", "71.20"], ["9999999999.99", "9999999999.99"]]) {
    const parsed = schema.parse({ ...valid, unit_price: input });
    assert.equal(parsed.unit_price, expected);
    assert.equal(parsed.scheme_code, null);
  }
});

test("tariff form rejects invalid prices, absent fields, invalid dates, category and control characters", () => {
  for (const unit_price of ["", "NaN", "1e2", "-1", "0.001", "10000000000", "1,000.00"]) {
    assert.equal(schema.safeParse({ ...valid, unit_price }).success, false, unit_price);
  }
  for (const override of [{ charge_code: " " }, { charge_code: "x".repeat(31) }, { scheme_code: "x".repeat(31) },
    { description: "" }, { description: "Invalid\0value" }, { charge_category: "guess" },
    { effective_from: "2026-02-30" }, { effective_from: "" }, { effective_from: "2026-09-09T00:00:00Z" }]) {
    assert.equal(schema.safeParse({ ...valid, ...override }).success, false, JSON.stringify(override));
  }
});

test("tariff route remains limited to billing and admin, not receptionist or platform admin", () => {
  const roles = load("../src/config/roles.ts", {}).ROLES;
  const routes = load("../src/lib/auth/routes.ts", { "@/config/roles": { ROLES: roles } });
  for (const role of Object.values(roles)) {
    assert.equal(routes.canRoleAccessPath(role, "/billing/tariffs"), ["billing", "admin"].includes(role), role);
  }
});
