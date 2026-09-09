import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

function harness() {
  const hooks = [], requests = [];
  let cursor = 0;
  const same = (a, b) => a && b.every((d, i) => Object.is(d, a[i]));
  const react = {
    useState(initial) {
      const i = cursor++;
      if (!(i in hooks)) hooks[i] = typeof initial === "function" ? initial() : initial;
      return [hooks[i], (next) => { hooks[i] = typeof next === "function" ? next(hooks[i]) : next; }];
    },
    useRef(initial) { return hooks[cursor++] ??= { current: initial }; },
    useCallback(fn, deps) {
      const i = cursor++;
      if (!same(hooks[i]?.deps, deps)) hooks[i] = { fn, deps };
      return hooks[i].fn;
    },
    useEffect(fn, deps) {
      const i = cursor++;
      if (!same(hooks[i]?.deps, deps)) hooks[i] = { fn, deps, cleanup: hooks[i]?.cleanup, pending: true };
    },
  };
  const source = readFileSync(new URL("../src/features/billing/hooks/useInvoicePayments.ts", import.meta.url), "utf8");
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const dependencies = { react,
    "../api": { getInvoiceDetail: (id) => new Promise((resolve, reject) => requests.push({ id, resolve, reject })) },
    "../lib/money": { DEFAULT_CURRENCY: "INR", moneyZero: () => ({ amount: "0.00", currency: "INR" }) },
  };
  const exports = {};
  new Function("require", "exports", code)((name) => { assert.ok(name in dependencies, name); return dependencies[name]; }, exports);
  return { requests,
    render(id, revision) { cursor = 0; return exports.useInvoicePayments(id, revision); },
    effects() { for (const h of hooks) if (h?.pending) { h.cleanup?.(); h.cleanup = h.fn(); h.pending = false; } },
    cleanup() { for (const h of hooks) h?.cleanup?.(); },
  };
}
const flush = () => new Promise((resolve) => setImmediate(resolve));
const detail = (amount, receipt = "A") => ({ net_amount: amount, total_paid: "0.00", total_refunded: "0.00", balance_due: amount, payments: [{ id: receipt }] });

test("payment balance invalidates immediately on invoice revision and reloads one coherent response", async () => {
  const ui = harness();
  ui.render("A", 1); ui.effects();
  ui.requests[0].resolve(detail("50.00")); await flush();
  assert.equal(ui.render("A", 1).balance_due.amount, "50.00");
  const changed = ui.render("A", 2);
  assert.equal(changed.loading, true);
  assert.deepEqual(changed.payments, []);
  assert.notEqual(changed.balance_due.amount, "50.00");
  ui.effects();
  assert.equal(ui.requests.length, 2, "One read per revision, not separate receipt and balance snapshots");
  ui.requests[1].resolve(detail("463.27")); await flush();
  assert.equal(ui.render("A", 2).balance_due.amount, "463.27");
  assert.equal(ui.render("A", 2).loading, false);
});

test("late prior invoice and revision responses cannot overwrite current receipts or balance", async () => {
  const ui = harness();
  ui.render("A", 1); ui.effects();
  ui.render("A", 2); ui.effects();
  ui.render("B", 2); ui.effects();
  ui.requests[2].resolve(detail("71.23", "B")); await flush();
  ui.requests[0].resolve(detail("50.00"));
  ui.requests[1].reject(new Error("Obsolete request")); await flush();
  const state = ui.render("B", 2);
  assert.equal(state.balance_due.amount, "71.23");
  assert.equal(state.payments[0].id, "B");
  assert.equal(state.error, null);
});

test("payment read failures are visible and retry does not revive an unmounted request", async () => {
  const ui = harness();
  ui.render("A", 1); ui.effects();
  ui.requests[0].reject(new Error("Balance unavailable")); await flush();
  assert.equal(ui.render("A", 1).error, "Balance unavailable");
  const retry = ui.render("A", 1).refresh();
  assert.equal(ui.render("A", 1).loading, true);
  ui.cleanup();
  ui.requests[1].resolve(detail("99.00")); await retry;
  assert.notEqual(ui.render("A", 1).balance_due.amount, "99.00");
});
