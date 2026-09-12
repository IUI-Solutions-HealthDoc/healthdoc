import assert from "node:assert/strict";
import test from "node:test";
import { compile, componentHarness, nodes, content, flush } from "./helpers/component-harness.mjs";
import { userFacingApiError } from "../src/lib/api-error-policy.mjs";

const { validateUserProfile } = compile(new URL("../src/features/admin/validation.ts", import.meta.url), {});
const staff = { full_name: "Synthetic Test Clinician", registration_number: "TEST-ONLY", registration_identifier_type: "REGNO1", registration_identifier_system: "https://registry.test" };

test("staff metadata must be complete and an explicit registry URI", () => {
  assert.deepEqual(validateUserProfile(staff), {});
  for (const field of ["registration_number", "registration_identifier_type", "registration_identifier_system"]) {
    assert.ok(validateUserProfile({ ...staff, [field]: null })[field]);
  }
  for (const system of ["registry.test", "javascript:alert(1)", "https://user:secret@registry.test", "https://registry.test?secret=1"]) {
    assert.ok(validateUserProfile({ ...staff, registration_identifier_system: system }).registration_identifier_system);
  }
  assert.deepEqual(validateUserProfile({ full_name: "Non-requesting staff" }), {});
});

test("missing requester errors are actionable without echoing professional or patient data", () => {
  const text = userFacingApiError(400, { code: "abdm_requester_required", message: "SECRET patient@sbx" });
  assert.match(text, /administrator.*registration/);
  assert.doesNotMatch(text, /SECRET|patient@sbx/);
});

for (const ready of [false, undefined, true]) {
  test(`workspace requester readiness ${ready} gates actual submission`, async (t) => {
    const priorDocument = globalThis.document, priorWindow = globalThis.window;
    globalThis.document = { hidden: false, addEventListener() {}, removeEventListener() {} };
    globalThis.window = { setInterval: () => 1, clearInterval() {} };
    t.after(() => { globalThis.document = priorDocument; globalThis.window = priorWindow; });
    const calls = [];
    const workspace = { patient_name: "Synthetic Patient", identity_verified: true, abha_address: "synthetic@sbx", requester_ready: ready, requests: [], next_offset: null };
    const ui = componentHarness((runtime) => compile(new URL("../src/features/doctor/abdm/AbdmWorkspace.tsx", import.meta.url), {
      ...runtime,
      "@/features/receptionist/api": { searchPatients: async () => ({ items: [{ id: "synthetic-patient", full_name: "Synthetic Patient", uhid: "TEST-ONLY" }] }) },
      "@/lib/api": { getUserFacingError: (_, fallback) => fallback, newIdempotencyKey: () => "test-key" },
      "./api": { HI_TYPES: ["WellnessRecord"], loadWorkspace: async () => workspace, askConsent: async (...args) => { calls.push(args); }, askRecords: async () => assert.fail("Unexpected records request") },
      "./ExternalRecordViewer": { ExternalRecordViewer: "viewer" },
      "./DocumentSharing": { DocumentSharing: "sharing" },
    }).AbdmWorkspace);
    let tree = ui.render({});
    const inputs = nodes(tree).filter((n) => n.type === "input");
    inputs[0].props.onChange({ target: { value: "Synthetic" } });
    inputs[1].props.onChange({ target: { value: "1990-01-01" } });
    tree = ui.render({});
    nodes(tree).find((n) => n.type === "form").props.onSubmit({ preventDefault() {} });
    await flush();
    tree = ui.render({});
    nodes(tree).find((n) => n.type === "button" && content(n).includes("TEST-ONLY")).props.onClick();
    tree = ui.render({}); ui.effects(); await flush(); tree = ui.render({});
    const fieldset = nodes(tree).find((n) => n.type === "fieldset" && "disabled" in n.props);
    assert.equal(fieldset.props.disabled, ready !== true);
    if (ready !== true) assert.match(content(tree), /requester profile is incomplete/);
    const dateInputs = nodes(tree).filter((n) => n.type === "input" && n.props.type === "datetime-local");
    ["2026-01-01T00:00", "2026-01-02T00:00", "2099-01-01T00:00"].forEach((value, i) => dateInputs[i].props.onChange({ target: { value } }));
    nodes(tree).find((n) => n.type === "input" && n.props.type === "checkbox").props.onChange({ target: { checked: true } });
    tree = ui.render({});
    // Invoke the handler even when the DOM fieldset is disabled: server/UI
    // business validation must not depend solely on a disabled button.
    nodes(tree).filter((n) => n.type === "form")[1].props.onSubmit({ preventDefault() {} });
    await flush();
    assert.equal(calls.length, ready === true ? 1 : 0);
    if (ready) {
      assert.deepEqual(calls[0][0].hi_types, ["WellnessRecord"]);
      assert.ok(!("requester" in calls[0][0]), "identity must come from the authenticated profile, not the browser");
    }
  });
}
