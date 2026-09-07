import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

function loadPayments() {
  const calls = [];
  const source = readFileSync(new URL("../src/features/billing/api/payments.ts", import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const exports = {};
  const dependencies = {
    "@/lib/api": { api: async (path, options) => { calls.push({ path, ...options }); }, newIdempotencyKey: () => "synthetic-key" },
    "../lib/money": { DEFAULT_CURRENCY: "INR" },
    "./invoices": {},
  };
  new Function("require", "exports", compiled)((name) => {
    assert.ok(name in dependencies, `Unexpected dependency ${name}`);
    return dependencies[name];
  }, exports);
  return { ...exports, calls };
}

test("payment and refund convert view money to decimal-string wire amounts", async () => {
  const api = loadPayments();
  await api.collectPayment("invoice", { amount: { amount: "1.25", currency: "INR" }, mode: "cash", currency: "INR" });
  await api.createRefund("payment", { amount: { amount: "0.25", currency: "INR" }, reason: "Synthetic reversal" });
  assert.equal(JSON.parse(api.calls[0].body).amount, "1.25");
  assert.equal(JSON.parse(api.calls[1].body).amount, "0.25");
  assert.ok(api.calls.every((call) => call.idempotencyKey));
});
