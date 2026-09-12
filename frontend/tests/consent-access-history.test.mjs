import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

// Execute the real role boundary and child rendering. This is not a browser test.
function harness() {
  const calls = [];
  let auth, result = { rows: [], loading: false, error: null, refresh() {} };
  const dependencies = {
    "react/jsx-runtime": {
      jsx: (type, props, key) => ({ type, props, key }),
      jsxs: (type, props, key) => ({ type, props, key }),
    },
    "@mui/material/Button": { default: "button" },
    "@mui/material/Typography": { default: "text" },
    "@/providers/auth-provider": { useAuth: () => auth },
    "../constants": { ACCESS_CHANNEL_LABELS: {} },
    "../hooks/useDataAccessLogs": { useDataAccessLogs: (id) => { calls.push(id); return result; } },
    "./DataAccessLogPanel": { DataAccessLogPanel: "ledger" },
  };
  const exports = {};
  const source = readFileSync(new URL("../src/features/consent/components/ConsentAccessHistory.tsx", import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  new Function("require", "exports", compiled)((name) => {
    assert.ok(name in dependencies, `Unexpected dependency ${name}`);
    return dependencies[name];
  }, exports);
  return {
    calls,
    setResult(value) { result = value; },
    render(role, consentId = "consent-A", isLoading = false, userId = "user-A") {
      auth = { user: role ? { id: userId, role } : null, isLoading };
      const boundary = exports.ConsentAccessHistory({ consentId });
      return { key: boundary.key, tree: typeof boundary.type === "function" ? boundary.type(boundary.props) : boundary };
    },
  };
}

for (const role of [null, "doctor", "nurse", "receptionist", "patient", "superadmin", "supervisor", "hod", "billing", "labtech", "radiology", "pharmacist", "emergency"]) {
  test(`${role ?? "anonymous"} never mounts the privileged ledger fetch`, () => {
    const ui = harness();
    assert.match(JSON.stringify(ui.render(role)), /available to facility administrators and auditors/);
    assert.deepEqual(ui.calls, []);
  });
}

for (const role of ["admin", "auditor"]) {
  test(`${role} loads only the selected consent after authentication settles`, () => {
    const ui = harness();
    ui.render(role, "consent-A", true);
    assert.deepEqual(ui.calls, []);
    const a = ui.render(role);
    assert.equal(a.tree.type, "ledger");
    assert.deepEqual(ui.calls, ["consent-A"]);
    assert.notEqual(a.key, ui.render(role, "consent-B").key);
    assert.notEqual(a.key, ui.render(role, "consent-A", false, "user-B").key);
    const count = ui.calls.length;
    ui.render("doctor");
    assert.equal(ui.calls.length, count);
  });
}

test("a permitted-role fetch failure is retryable and never displayed as an empty ledger", () => {
  const ui = harness();
  let retries = 0;
  ui.setResult({ rows: [], loading: false, error: "Permission refused", refresh() { retries++; } });
  const { tree } = ui.render("admin");
  assert.match(JSON.stringify(tree), /Access history could not be loaded/);
  assert.doesNotMatch(JSON.stringify(tree), /"ledger"/);
  tree.props.children.find((node) => node.type === "button").props.onClick();
  assert.equal(retries, 1);
});
