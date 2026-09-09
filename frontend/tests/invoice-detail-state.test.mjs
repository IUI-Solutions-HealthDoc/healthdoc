import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

function harness() {
  const hooks = [], requests = [];
  let cursor = 0;
  const same = (a, b) => a && a.length === b.length && b.every((d, i) => Object.is(d, a[i]));
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
  const source = readFileSync(new URL("../src/features/billing/hooks/useInvoiceDetail.ts", import.meta.url), "utf8");
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const dependencies = { react, "../api": {
    getInvoice: (id) => new Promise((resolve, reject) => requests.push({ id, resolve, reject })),
  } };
  const exports = {};
  new Function("require", "exports", code)((name) => { assert.ok(name in dependencies, name); return dependencies[name]; }, exports);
  return { requests,
    render(id) { cursor = 0; return exports.useInvoiceDetail(id); },
    effects() { for (const h of hooks) if (h?.pending) { h.cleanup?.(); h.cleanup = h.fn(); h.pending = false; } },
    cleanup() { for (const h of hooks) h?.cleanup?.(); },
    replay() { for (const h of hooks) if (h && "pending" in h) { h.cleanup?.(); h.cleanup = h.fn(); } },
  };
}
const flush = () => new Promise((resolve) => setImmediate(resolve));
const row = (id, row_version = 1) => ({ id, row_version, patient_id: `patient-${id}` });

test("invoice detail clears the old identity before effects on a selection change", async () => {
  const ui = harness(); ui.render("A"); ui.effects();
  ui.requests[0].resolve(row("A")); await flush();
  assert.equal(ui.render("A").invoice.id, "A");
  assert.equal(ui.render("B").invoice, null);
  assert.equal(ui.render("B").loading, true);
});

test("late invoice reads and failures cannot replace a different selected invoice", async () => {
  const ui = harness(); ui.render("A"); ui.effects();
  ui.render("B"); ui.effects();
  ui.requests[1].resolve(row("B")); await flush();
  ui.requests[0].resolve(row("A")); await flush();
  assert.equal(ui.render("B").invoice.id, "B");
  const pending = ui.render("B").refresh();
  ui.render("C"); ui.effects();
  ui.requests[3].resolve(row("C")); await flush();
  ui.requests[2].reject(new Error("Old request")); await pending;
  assert.equal(ui.render("C").invoice.id, "C");
  assert.equal(ui.render("C").error, null);
});

test("mutation results invalidate prior reads and reject a mismatched invoice", async () => {
  const ui = harness(); ui.render("A"); ui.effects();
  ui.render("A").setInvoice(row("A", 2));
  ui.requests[0].resolve(row("A", 1)); await flush();
  assert.equal(ui.render("A").invoice.row_version, 2);
  ui.render("A").setInvoice(row("B"));
  assert.equal(ui.render("A").invoice, null);
  assert.match(ui.render("A").error, /invoice/i);
});

test("mismatched detail responses fail closed and selected-invoice errors are retryable", async () => {
  const ui = harness(); ui.render("A"); ui.effects();
  ui.requests[0].resolve(row("B")); await flush();
  assert.equal(ui.render("A").invoice, null);
  assert.match(ui.render("A").error, /invoice/i);
  const retry = ui.render("A").refresh();
  ui.requests[1].resolve(row("A")); await retry;
  assert.equal(ui.render("A").invoice.id, "A");
  assert.equal(ui.render("A").error, null);
});

test("clearing selection and cleanup invalidate in-flight invoice reads", async () => {
  const ui = harness(); ui.render("A"); ui.effects();
  ui.render(null); ui.effects();
  ui.requests[0].resolve(row("A")); await flush();
  assert.equal(ui.render(null).invoice, null);
  assert.equal(ui.render(null).loading, false);
  ui.render("B"); ui.effects(); ui.cleanup();
  ui.requests[1].resolve(row("B")); await flush();
  assert.equal(ui.render("B").invoice, null);
});

test("callbacks retained by the previous selection cannot invalidate the new invoice", async () => {
  const ui = harness(); const old = ui.render("A"); ui.effects();
  ui.render("B"); ui.effects();
  ui.requests[1].resolve(row("B")); await flush();
  old.setInvoice(row("A", 3)); await old.refresh();
  assert.equal(ui.requests.length, 2, "Obsolete callbacks must not start another read");
  assert.equal(ui.render("B").invoice.id, "B");
});

test("StrictMode effect replay ignores the first request and accepts the replayed read", async () => {
  const ui = harness(); ui.render("A"); ui.effects(); ui.replay();
  ui.requests[1].resolve(row("A", 2)); await flush();
  ui.requests[0].reject(new Error("Discarded replay request")); await flush();
  assert.equal(ui.render("A").invoice.row_version, 2);
  assert.equal(ui.render("A").error, null);
});
