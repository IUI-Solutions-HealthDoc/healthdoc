import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

// Exercise the component's actual effect with deferred transport, without
// pretending these hook-level regressions replace the real browser CI gate.
function componentHarness() {
  const state = [], calls = [];
  let cursor = 0, effect;
  const react = {
    useState(initial) {
      const index = cursor++;
      if (!(index in state)) state[index] = initial;
      return [state[index], (value) => { state[index] = typeof value === "function" ? value(state[index]) : value; }];
    },
    useEffect(callback) { effect = callback; },
  };
  const source = readFileSync(new URL("../src/features/admin/AbdmDeliveryJobs.tsx", import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  const exports = {};
  const dependencies = {
    react,
    "react/jsx-runtime": { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) },
    "@/lib/api": {
      api: (path, options) => new Promise((resolve, reject) => calls.push({ path, options, resolve, reject })),
      getUserFacingError: (_error, fallback) => fallback,
      newIdempotencyKey: () => "synthetic-key",
    },
  };
  new Function("require", "exports", compiled)((name) => {
    assert.ok(name in dependencies, `Unexpected dependency ${name}`);
    return dependencies[name];
  }, exports);
  return {
    calls,
    render() { cursor = 0; return exports.AbdmDeliveryJobs(); },
    startEffect() { return effect(); },
  };
}

function nodes(tree) {
  if (!tree || typeof tree !== "object") return [];
  return [tree, ...[tree.props?.children].flat(Infinity).flatMap(nodes)];
}
const flush = () => new Promise((resolve) => setImmediate(resolve));

test("jobs effect replay completes GETs and ignores stale responses", async () => {
  const ui = componentHarness();
  ui.render();
  ui.startEffect()(); // Strict Mode cleanup before the replacement effect.
  const cleanup = ui.startEffect();
  assert.equal(ui.calls.length, 2);
  assert.ok(ui.calls.every((call) => !call.options?.signal?.aborted));
  ui.calls[1].resolve([{ id: "new", kind: "hiu_fetch", status: "dead", attempts: 1, last_error: null }]);
  await flush();
  ui.calls[0].resolve([{ id: "old", kind: "hip_transfer", status: "dead", attempts: 9, last_error: null }]);
  await flush();
  const output = JSON.stringify(ui.render());
  assert.ok(output.includes("hiu_fetch"));
  assert.ok(!output.includes("hip_transfer"));
  cleanup();
});

test("failed jobs read stays visible and a successful refresh clears it", async () => {
  const ui = componentHarness();
  ui.render();
  const cleanup = ui.startEffect();
  ui.calls[0].reject(new Error("synthetic transport failure"));
  await flush();
  assert.equal(nodes(ui.render()).filter((node) => node.props?.role === "alert").length, 1);
  assert.ok(!JSON.stringify(ui.render()).includes("No jobs in this page."));
  cleanup();
  ui.startEffect();
  assert.ok(JSON.stringify(ui.render()).includes("Loading delivery jobs"));
  ui.calls[1].resolve([]);
  await flush();
  assert.equal(nodes(ui.render()).filter((node) => node.props?.role === "alert").length, 0);
  assert.ok(JSON.stringify(ui.render()).includes("No jobs in this page."));
});

test("cleanup prevents stale failures from overwriting a successful jobs read", async () => {
  const ui = componentHarness();
  ui.render();
  ui.startEffect()();
  ui.startEffect();
  ui.calls[1].resolve([]);
  await flush();
  ui.calls[0].reject(new Error("obsolete failure"));
  await flush();
  assert.equal(nodes(ui.render()).filter((node) => node.props?.role === "alert").length, 0);
});
