import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

// Execute the real TSX with deferred transport. This minimal hook/key harness
// tests component state and cleanup, not layout, hydration or real SSO.
function compile(file, dependencies) {
  const source = readFileSync(new URL(file, import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  const exports = {};
  new Function("require", "exports", compiled)((name) => {
    assert.ok(name in dependencies, `Unexpected dependency ${name}`);
    return dependencies[name];
  }, exports);
  return exports;
}

function harness(kind) {
  const calls = [], fibers = new Map();
  let fiber, cursor, seen;
  const react = {
    useState(initial) {
      const owner = fiber, i = cursor++;
      if (!(i in owner.hooks)) owner.hooks[i] = typeof initial === "function" ? initial() : initial;
      return [owner.hooks[i], (value) => {
        owner.hooks[i] = typeof value === "function" ? value(owner.hooks[i]) : value;
      }];
    },
    useRef(initial) {
      const i = cursor++;
      return fiber.hooks[i] ??= { current: initial };
    },
    useEffect(callback, deps) {
      const i = cursor++;
      const old = fiber.hooks[i];
      if (!old || deps.some((dep, index) => !Object.is(dep, old.deps[index]))) {
        fiber.hooks[i] = { effect: callback, deps, cleanup: old?.cleanup, pending: true };
      }
    },
  };
  const request = (name) => (...args) => new Promise((resolve, reject) => calls.push({ name, args, resolve, reject }));
  const dependencies = {
    react,
    "react/jsx-runtime": {
      jsx: (type, props, key) => ({ type, props, key }),
      jsxs: (type, props, key) => ({ type, props, key }),
    },
    "@/lib/api": { ApiError: class extends Error {}, newIdempotencyKey: () => "synthetic-key" },
  };
  let component;
  if (kind === "abha") {
    dependencies["./api"] = Object.fromEntries([
      "requestAbhaLoginOtp", "requestAbhaEnrolmentOtp", "verifyAbhaLoginOtp", "verifyAbhaEnrolmentOtp",
    ].map((name) => [name, request(name)]));
    dependencies["./patientValidation"] = compile("../src/features/receptionist/patientValidation.ts", {});
    component = compile("../src/features/receptionist/AbhaIdentityPanel.tsx", dependencies).AbhaIdentityPanel;
  } else if (kind === "access") {
    for (const name of ["Alert", "Box", "CircularProgress", "Stack", "Typography"]) dependencies[`@mui/material/${name}`] = name;
    dependencies["@/components/ui/Button"] = { Button: "button" };
    dependencies["@/styles/theme"] = { meridian: {} };
    dependencies["../panelSx"] = { doctorPanelSx: {}, doctorButtonSx: {} };
    dependencies["./BreakGlassBanner"] = { BreakGlassBanner: "banner" };
    dependencies["./BreakGlassWarningModal"] = { BreakGlassWarningModal: "modal" };
    // Deliberately no cancellation in the mocked hook: the actual boundary
    // must isolate late hook state and open dialogs between patients.
    dependencies["../hooks/useBreakGlass"] = { useBreakGlass(id) {
      const [access, setAccess] = react.useState(null);
      react.useEffect(() => { request("access")(id).then(setAccess); }, [id]);
      return { allowed: access?.allowed ?? false, mfaVerified: true };
    } };
    component = compile("../src/features/doctor/components/BreakGlassGate.tsx", dependencies).BreakGlassGate;
  } else {
    for (const name of ["Box", "Divider", "Stack", "Typography"]) dependencies[`@mui/material/${name}`] = name;
    dependencies["next/link"] = "Link";
    dependencies["@/components/ui/Button"] = { Button: "button" };
    dependencies["@/components/ui/StatusChip"] = { StatusChip: "StatusChip" };
    dependencies["@/styles/theme"] = { meridian: {} };
    dependencies["../panelSx"] = { doctorPanelSx: {} };
    dependencies["../lib/formatters"] = { formatAgeSex: () => "Synthetic age/sex" };
    dependencies["../api"] = Object.fromEntries(["getPatient", "getPatientHistory", "listAllergies"].map((name) => [name, request(name)]));
    component = compile("../src/features/doctor/components/PatientSummarySidebar.tsx", dependencies).PatientSummarySidebar;
  }
  function expand(node, position) {
    if (Array.isArray(node)) return node.map((child, i) => expand(child, `${position}/${i}`));
    if (!node || typeof node !== "object") return node;
    if (typeof node.type === "function") {
      const id = `${position}/${node.type.name}/${node.key ?? ""}`;
      seen.add(id);
      const owner = fibers.get(id) ?? { hooks: [] };
      fibers.set(id, owner);
      fiber = owner;
      cursor = 0;
      return expand(node.type(node.props), id);
    }
    return { ...node, props: { ...node.props, children: expand(node.props?.children, `${position}/children`) } };
  }
  return {
    calls,
    render(props) {
      seen = new Set();
      const tree = expand({ type: component, props }, "root");
      for (const [id, owner] of fibers) if (!seen.has(id)) {
        owner.hooks.forEach((hook) => hook?.cleanup?.());
        fibers.delete(id);
      }
      return tree;
    },
    effects() {
      for (const owner of fibers.values()) for (const hook of owner.hooks) if (hook?.pending) {
        hook.cleanup?.();
        hook.cleanup = hook.effect();
        hook.pending = false;
      }
    },
    strictReplay() {
      for (const owner of fibers.values()) for (const hook of owner.hooks) if (hook?.effect) {
        hook.cleanup?.();
        hook.cleanup = hook.effect();
      }
    },
  };
}

function nodes(tree) {
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return tree && typeof tree === "object" ? [tree, ...nodes(tree.props?.children)] : [];
}
function text(tree) {
  if (Array.isArray(tree)) return tree.map(text).join(" ");
  return tree && typeof tree === "object" ? text(tree.props?.children) : String(tree ?? "");
}
const button = (tree, label) => nodes(tree).find((node) => node.type === "button" && text(node) === label);
const flush = () => new Promise((resolve) => setImmediate(resolve));
const patient = (id) => ({ patient: { id, full_name: `Patient ${id}`, abha_number: id === "A" ? "91000000000001" : "91000000000002" } });
const token = (id) => ({ token: { id: `token-${id}`, patient_id: id, full_name: `Queue ${id}`, token_display: id, status: "waiting" } });

test("record access boundary cannot reuse another patient's grant, pending response or open dialog", async () => {
  const ui = harness("access");
  const props = (id) => ({ patient: token(id).token, children: `Protected chart ${id}` });
  ui.render(props("A")); ui.effects();
  ui.calls[0].resolve({ allowed: true }); await flush();
  assert.match(text(ui.render(props("A"))), /Protected chart A/);
  assert.doesNotMatch(text(ui.render(props("B"))), /Protected chart/);
  ui.effects();
  ui.render(props("C")); ui.effects();
  ui.calls[2].resolve({ allowed: false }); await flush();
  let tree = ui.render(props("C"));
  button(tree, "Emergency access").props.onClick();
  assert.equal(nodes(ui.render(props("C"))).find((n) => n.type === "modal").props.open, true);
  tree = ui.render(props("D")); ui.effects();
  assert.equal(nodes(tree).find((n) => n.type === "modal").props.open, false);
  ui.calls[3].resolve({ allowed: false });
  ui.calls[1].resolve({ allowed: true }); await flush();
  tree = ui.render(props("D"));
  assert.match(text(tree), /Record locked/);
  assert.doesNotMatch(text(tree), /Protected chart/);
});
function summaryResult(call, id) {
  if (call.name === "getPatient") return { full_name: `Full ${id}`, uhid: `UHID-${id}` };
  if (call.name === "listAllergies") return [{ id, substance_text: `Allergy ${id}`, severity: "mild" }];
  return [{ visit_id: id, visit_date: "2026-06-01", diagnoses: [`Diagnosis ${id}`] }];
}

test("doctor switches patients before paint and ignores old successful or failed reads", async () => {
  const ui = harness("doctor");
  ui.render(token("A")); ui.effects();
  ui.calls.forEach((call) => call.resolve(summaryResult(call, "A")));
  await flush();
  assert.match(text(ui.render(token("A"))), /Allergy A/);
  const switched = text(ui.render(token("B")));
  assert.doesNotMatch(switched, /Full A|Allergy A|Diagnosis A|First visit|None recorded/);
  ui.effects();
  ui.render(token("C")); ui.effects();
  ui.calls.slice(6).forEach((call) => call.resolve(summaryResult(call, "C")));
  await flush();
  ui.calls[3].resolve(summaryResult(ui.calls[3], "B"));
  ui.calls[4].reject(new Error("old request failed"));
  ui.calls[5].resolve(summaryResult(ui.calls[5], "B"));
  await flush();
  const final = text(ui.render(token("C")));
  assert.match(final, /Allergy C/);
  assert.doesNotMatch(final, /Full B|Allergy B|unavailable/);
});

for (const failedRead of ["getPatient", "getPatientHistory", "listAllergies"]) {
  test(`doctor ${failedRead} failure is unknown, retryable and StrictMode-safe`, async () => {
    const ui = harness("doctor");
    ui.render(token("A")); ui.effects(); ui.strictReplay();
    ui.calls.slice(3).forEach((call) => call.name === failedRead ? call.reject(new Error("synthetic")) : call.resolve(summaryResult(call, "A")));
    await flush();
    ui.calls.slice(0, 3).forEach((call) => call.resolve(summaryResult(call, "obsolete")));
    await flush();
    let tree = ui.render(token("A"));
    assert.match(text(tree), /unavailable/);
    assert.doesNotMatch(text(tree), /obsolete|None recorded|First visit/);
    button(tree, "Retry patient summary").props.onClick();
    tree = ui.render(token("A")); ui.effects();
    assert.match(text(tree), /Loading/);
    ui.calls.slice(6).forEach((call) => call.resolve(call.name === "getPatient" ? summaryResult(call, "A") : []));
    await flush();
    tree = ui.render(token("A"));
    assert.doesNotMatch(text(tree), /unavailable/);
    assert.match(text(tree), /None recorded/);
  });
}

test("ABHA patient change clears entered OTP and rejects late patient/flow responses", async () => {
  const ui = harness("abha");
  let tree = ui.render(patient("A")); ui.effects(); ui.strictReplay();
  const pending = button(tree, "Send OTP").props.onClick();
  // Duplicate event before React can disable the button must not send twice.
  button(tree, "Send OTP").props.onClick();
  assert.equal(ui.calls.length, 1);
  ui.calls[0].resolve({ session_id: "session-A", masked_mobile: "masked-A" });
  await pending; await flush();
  tree = ui.render(patient("A"));
  nodes(tree).find((node) => node.type === "input").props.onChange({ target: { value: "123456" } });
  tree = ui.render(patient("A"));
  button(tree, "Verify and link").props.onClick();
  tree = ui.render(patient("B")); ui.effects();
  assert.doesNotMatch(text(tree), /masked-A|verified and linked/);
  assert.deepEqual(nodes(tree).filter((node) => node.type === "input").map((node) => node.props.value), ["91000000000002"]);
  ui.calls[1].resolve({ linked: true, linked_patient_id: "A", abha_number: "old-A" });
  await flush();
  tree = ui.render(patient("B"));
  assert.doesNotMatch(text(tree), /old-A|verified and linked/);
  button(tree, "Send OTP").props.onClick();
  button(tree, "Create ABHA").props.onClick();
  ui.calls[2].resolve({ session_id: "obsolete-B", masked_mobile: "obsolete-mobile" });
  await flush();
  tree = ui.render(patient("B"));
  assert.match(text(tree), /Aadhaar number/);
  assert.doesNotMatch(text(tree), /obsolete-mobile/);
  assert.equal(button(tree, "Verify and link"), undefined);
});

test("ABHA late error after switching flow cannot overwrite the replacement flow", async () => {
  const ui = harness("abha");
  let tree = ui.render(patient("A")); ui.effects();
  button(tree, "Send OTP").props.onClick();
  button(tree, "Create ABHA").props.onClick();
  ui.calls[0].reject(new Error("obsolete")); await flush();
  tree = ui.render(patient("A"));
  assert.equal(nodes(tree).filter((node) => node.props?.role === "alert").length, 0);
});

test("ABHA refuses a mismatched binding and a confirmed success is discarded on patient switch", async () => {
  for (const linkedPatient of ["A", "B"]) {
    const ui = harness("abha");
    let tree = ui.render(patient("A")); ui.effects();
    button(tree, "Send OTP").props.onClick();
    ui.calls[0].resolve({ session_id: "session-A", masked_mobile: "masked-A" });
    await flush(); tree = ui.render(patient("A"));
    nodes(tree).find((node) => node.type === "input").props.onChange({ target: { value: "123456" } });
    tree = ui.render(patient("A"));
    button(tree, "Verify and link").props.onClick();
    ui.calls[1].resolve({ linked: true, linked_patient_id: linkedPatient, abha_number: "confirmed-A" });
    await flush(); tree = ui.render(patient("A"));
    if (linkedPatient === "A") assert.match(text(tree), /ABHA verified and linked/);
    else assert.match(text(tree), /did not confirm identity binding/);
    tree = ui.render(patient("B")); ui.effects();
    assert.doesNotMatch(text(tree), /confirmed-A|did not confirm|verified and linked/);
  }
});

test("a missing doctor patient read is unavailable, not a successfully empty chart", async () => {
  const ui = harness("doctor");
  ui.render(token("A")); ui.effects();
  ui.calls[0].resolve(null);
  ui.calls[1].resolve([]);
  ui.calls[2].resolve([]);
  await flush();
  assert.match(text(ui.render(token("A"))), /Patient details unavailable/);
});
