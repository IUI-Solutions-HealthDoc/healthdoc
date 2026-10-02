import assert from "node:assert/strict";
import test from "node:test";
import { compile, componentHarness, content, flush, nodes } from "./helpers/component-harness.mjs";

/** Reception ABHA desk: workbook CRT_ABHA_106 (resend), VRFY_ABHA_101/401
 * (Aadhaar-OTP verification of an existing ABHA) and VRFY_ABHA_304/402/305/405
 * (wrong OTP, resend). Synthetic transport; no gateway, OTP or identifier leaves
 * this process. */

// The panel ticks its resend countdown with setInterval. The harness never
// unmounts, so a live interval would keep the test process alive; the tests
// drive Date.now and re-render explicitly instead.
const realTimers = { setInterval: globalThis.setInterval, clearInterval: globalThis.clearInterval };
const intervals = new Map();
globalThis.setInterval = (fn) => { const id = intervals.size + 1; intervals.set(id, fn); return id; };
globalThis.clearInterval = (id) => { intervals.delete(id); };
const tickTimers = () => { for (const fn of intervals.values()) fn(); };
test.after(() => Object.assign(globalThis, realTimers));

class TestApiError extends Error {
  constructor(code, message, payload) { super(message); this.code = code; this.payload = payload; }
}
const source = (path) => new URL(`../src/features/receptionist/${path}`, import.meta.url);
const find = (tree, predicate) => nodes(tree).find(predicate);
const button = (tree, text) => find(tree, (n) => n.type === "button" && content(n).replace(/\s+/g, " ").trim().startsWith(text));
const input = (tree) => find(tree, (n) => n.type === "input");
const alertText = (tree) => nodes(tree).filter((n) => n.props?.role === "alert").map(content).join(" ");

/** The panel's own child modules, compiled for real against the same stubs. */
function panelParts(runtime, api) {
  const consent = compile(source("AbhaConsentDeclaration.tsx"), runtime);
  const demographic = compile(source("DemographicAbhaEnrolment.tsx"), {
    ...runtime,
    "@/lib/api": { ApiError: TestApiError, newIdempotencyKey: () => "synthetic-key" },
    "./AbhaConsentDeclaration": consent,
    "./api": api,
    "./patientValidation": compile(source("patientValidation.ts"), {}),
  });
  return { "./AbhaConsentDeclaration": consent, "./DemographicAbhaEnrolment": demographic };
}

function desk(apiStubs) {
  const calls = [];
  const record = (name, impl) => async (...args) => { calls.push({ name, args }); return impl(...args); };
  const api = Object.fromEntries(Object.entries(apiStubs).map(([name, impl]) => [name, record(name, impl)]));
  const h = componentHarness((runtime) => compile(source("AbhaIdentityPanel.tsx"), {
    ...runtime,
    "@/lib/api": { ApiError: TestApiError, newIdempotencyKey: () => "synthetic-key" },
    "./api": api,
    "./patientValidation": compile(source("patientValidation.ts"), {}),
    ...panelParts(runtime, api),
  }).AbhaIdentityPanel);
  const props = { patient: { id: "patient-A", full_name: "Synthetic Patient", abha_number: null } };
  const render = () => { const tree = h.render(props); h.effects(); return tree; };
  return { calls, render };
}

test("existing ABHA can be verified through Aadhaar OTP and the desk resends within limits", async () => {
  let sessions = 0;
  const d = desk({
    requestAbhaLoginOtp: async () => ({ session_id: `s${++sessions}`, masked_mobile: "OTP sent to ******1234", resends_remaining: 3 }),
    resendAbhaOtp: async () => ({ session_id: `s${++sessions}`, masked_mobile: "OTP sent to ******1234", resends_remaining: 2 }),
    verifyAbhaLoginOtp: async () => { throw new TestApiError(400, "ABDM did not accept this OTP.", { code: "otp_rejected" }); },
    requestAbhaEnrolmentOtp: async () => { throw new Error("not this flow"); },
    verifyAbhaEnrolmentOtp: async () => { throw new Error("not this flow"); },
  });
  let tree = d.render();
  button(tree, "OTP through Aadhaar").props.onClick();
  tree = d.render();
  assert.match(content(tree), /Aadhaar number/);
  input(tree).props.onChange({ target: { value: "9999 8888 7777" } });
  tree = d.render();
  await button(tree, "Send OTP").props.onClick(); await flush();
  tree = d.render();
  assert.deepEqual(d.calls[0], { name: "requestAbhaLoginOtp", args: ["patient-A", { aadhaar: "999988887777" }, "synthetic-key"] });
  assert.doesNotMatch(content(tree), /999988887777/, "the Aadhaar number must leave the screen once the OTP step begins");

  // Fresh request: resend is offered but inside the cooldown.
  const resend = button(tree, "Resend OTP");
  assert.ok(resend, "resend control must exist while the session is open");
  assert.equal(resend.props.disabled, true);
  assert.match(content(resend), /Resend OTP in \d+s/);

  // A wrong OTP is a correctable refusal: same session, empty code field, message shown.
  const otpField = nodes(tree).filter((n) => n.type === "input").at(-1);
  otpField.props.onChange({ target: { value: "000000" } });
  tree = d.render();
  await button(tree, "Verify and link").props.onClick(); await flush();
  tree = d.render();
  assert.match(alertText(tree), /did not accept this OTP/);
  assert.equal(nodes(tree).filter((n) => n.type === "input").at(-1).props.value, "");
  assert.ok(button(tree, "Verify and link"), "the session survives a refused OTP");
  assert.equal(d.calls.filter((c) => c.name === "verifyAbhaLoginOtp")[0].args[0], "s1");
});

test("a resend re-supplies the identifier from memory, swaps to the new session and honours the server's cooldown and cap", async () => {
  let sessions = 0;
  const resendResponses = [
    () => ({ session_id: `s${++sessions}`, masked_mobile: null, resends_remaining: 2 }),
    () => { throw new TestApiError(429, "Wait 30 seconds before requesting another OTP", { code: "otp_resend_too_soon", retry_after_seconds: 30 }); },
    () => { throw new TestApiError(429, "No more OTP resends for this attempt.", { code: "otp_resend_exhausted" }); },
  ];
  const d = desk({
    requestAbhaLoginOtp: async () => ({ session_id: `s${++sessions}`, masked_mobile: null, resends_remaining: 3 }),
    resendAbhaOtp: async () => resendResponses.shift()(),
    verifyAbhaLoginOtp: async (sessionId) => ({ linked: true, linked_patient_id: "patient-A", abha_number: "91-1111-2222-3333", session: sessionId }),
    requestAbhaEnrolmentOtp: async () => { throw new Error("not this flow"); },
    verifyAbhaEnrolmentOtp: async () => { throw new Error("not this flow"); },
  });
  const realNow = Date.now;
  let clock = 1_000_000;
  Date.now = () => clock;
  try {
    let tree = d.render();
    input(tree).props.onChange({ target: { value: "91-1111-2222-3333" } });
    tree = d.render();
    await button(tree, "Send OTP").props.onClick(); await flush();
    tree = d.render();
    assert.equal(button(tree, "Resend OTP").props.disabled, true, "cooldown right after the first OTP");

    clock += 31_000; tickTimers(); tree = d.render();
    const resend = button(tree, "Resend OTP");
    assert.equal(resend.props.disabled, false);
    assert.match(content(resend), /3 left/);
    await resend.props.onClick(); await flush();
    tree = d.render();
    const resendCall = d.calls.find((c) => c.name === "resendAbhaOtp");
    assert.deepEqual(resendCall.args, ["existing", "patient-A", "s1", { abha_number: "91-1111-2222-3333" }, "synthetic-key"]);
    assert.match(content(button(tree, "Resend OTP")), /Resend OTP in \d+s/, "a new cooldown starts after a resend");

    // Verify now uses the NEW session, never the spent one.
    nodes(tree).filter((n) => n.type === "input").at(-1).props.onChange({ target: { value: "123456" } });
    tree = d.render();
    clock += 31_000; tickTimers(); tree = d.render();
    // Server says too soon (its clock is authoritative): the desk backs off for the stated seconds.
    await button(tree, "Resend OTP").props.onClick(); await flush();
    tree = d.render();
    assert.match(alertText(tree), /Wait 30 seconds/);
    assert.equal(button(tree, "Resend OTP").props.disabled, true);
    clock += 31_000; tickTimers(); tree = d.render();
    await button(tree, "Resend OTP").props.onClick(); await flush();
    tree = d.render();
    assert.match(content(tree), /No more OTP resends for this attempt/);
    assert.equal(button(tree, "Resend OTP"), undefined);

    await button(tree, "Verify and link").props.onClick(); await flush();
    tree = d.render();
    assert.equal(d.calls.filter((c) => c.name === "verifyAbhaLoginOtp").at(-1).args[0], "s2");
    assert.match(content(tree), /ABHA verified and linked/);
  } finally {
    Date.now = realNow;
  }
});

test("switching patient discards the remembered identifier and open session", async () => {
  const d = desk({
    requestAbhaLoginOtp: async () => ({ session_id: "s1", masked_mobile: null, resends_remaining: 3 }),
    resendAbhaOtp: async () => { throw new Error("must not be reachable after a patient switch"); },
    verifyAbhaLoginOtp: async () => { throw new Error("unused"); },
    requestAbhaEnrolmentOtp: async () => { throw new Error("unused"); },
    verifyAbhaEnrolmentOtp: async () => { throw new Error("unused"); },
  });
  let tree = d.render();
  button(tree, "OTP through Aadhaar").props.onClick();
  tree = d.render();
  input(tree).props.onChange({ target: { value: "999988887777" } });
  tree = d.render();
  await button(tree, "Send OTP").props.onClick(); await flush();
  tree = d.render();
  assert.ok(button(tree, "Resend OTP"));
  const h = componentHarness((runtime) => compile(source("AbhaIdentityPanel.tsx"), {
    ...runtime, "@/lib/api": { ApiError: TestApiError, newIdempotencyKey: () => "k" },
    "./api": {}, "./patientValidation": compile(source("patientValidation.ts"), {}),
    ...panelParts(runtime, {}),
  }).AbhaIdentityPanel);
  const other = h.render({ patient: { id: "patient-B", full_name: "Other Patient", abha_number: null } }); h.effects();
  assert.equal(button(other, "Resend OTP"), undefined);
  assert.ok(button(other, "Send OTP"), "a new patient starts from the identifier step");
  assert.doesNotMatch(content(other), /999988887777/);
});

/** NHA's published statements, as the server renders them (texts shortened). */
const DECLARATION = {
  version: "nha-consent-language-1", ownership: "government", language: "en", notice: null,
  intro: "I hereby declare that:", sha256: "a".repeat(64),
  statements: [
    { id: "aadhaar_sharing", text: "I am voluntarily sharing my Aadhaar Number", ticked: true, required: true },
    { id: "other_document", text: "using document other than Aadhaar.", ticked: false, required: false },
    { id: "link_records", text: "linking of my legacy (past) government health records", ticked: true, required: null },
    { id: "share_for_care", text: "I authorize the sharing of all my health records", ticked: true, required: null },
    { id: "anonymised_use", text: "anonymization and subsequent use of my government health records", ticked: true, required: null },
    { id: "health_worker", text: "I, Synthetic Receptionist, confirm that I have duly informed", ticked: false, required: true },
    { id: "beneficiary", text: "I, Synthetic Patient, have been explained about the consent", ticked: false, required: true },
  ],
};
const tick = (tree, id, checked = true) =>
  find(tree, (n) => n.type === "input" && n.props.type === "checkbox" && n.props.name === id).props.onChange({ target: { checked } });

async function openNewAbha(d) {
  let tree = d.render();
  button(tree, "Create ABHA").props.onClick();
  d.render(); await flush();
  tree = d.render();
  input(tree).props.onChange({ target: { value: "999988887777" } });
  return d.render();
}

test("the desk shows NHA's published consent and sends only once both confirmations are ticked", async () => {
  const d = desk({
    getAbhaEnrolmentDeclaration: async () => DECLARATION,
    requestAbhaEnrolmentOtp: async () => ({ session_id: "s1", masked_mobile: null, resends_remaining: 3 }),
  });
  let tree = await openNewAbha(d);
  assert.deepEqual(d.calls[0], { name: "getAbhaEnrolmentDeclaration", args: ["patient-A", "en"] });
  assert.match(content(tree), /I hereby declare that:/);
  for (const statement of DECLARATION.statements) assert.ok(content(tree).includes(statement.text));
  const ticked = (id) => find(tree, (n) => n.type === "input" && n.props.name === id).props.checked;
  assert.deepEqual(DECLARATION.statements.map((s) => ticked(s.id)), [true, false, true, true, true, false, false],
    "NHA's form ticks 1, 3, 4 and 5; the confirmations start empty");
  assert.equal(button(tree, "Send OTP").props.disabled, true);
  tick(tree, "health_worker"); tree = d.render();
  assert.equal(button(tree, "Send OTP").props.disabled, true, "the patient's own confirmation is still missing");
  tick(tree, "beneficiary"); tree = d.render();
  tick(tree, "anonymised_use", false); tree = d.render();
  assert.equal(button(tree, "Send OTP").props.disabled, false, "optional statements may be declined");

  tick(tree, "other_document"); tree = d.render();
  assert.equal(button(tree, "Send OTP").props.disabled, true);
  assert.match(alertText(tree), /document other than Aadhaar/);
  tick(tree, "other_document", false); tree = d.render();

  await button(tree, "Send OTP").props.onClick(); await flush();
  const sent = d.calls.find((c) => c.name === "requestAbhaEnrolmentOtp").args[2];
  assert.equal(sent.code, "abha-enrollment");
  assert.equal(sent.declaration_sha256, DECLARATION.sha256);
  assert.deepEqual(sent.statements, {
    aadhaar_sharing: true, other_document: false, link_records: true, share_for_care: true,
    anonymised_use: false, health_worker: true, beneficiary: true,
  });
});

test("a consent that cannot be loaded is a refusal, not a blank form", async () => {
  const d = desk({
    getAbhaEnrolmentDeclaration: async () => {
      throw new TestApiError(409, "Record whether this facility is government or private before creating ABHAs", { code: "facility_ownership_unset" });
    },
    requestAbhaEnrolmentOtp: async () => { throw new Error("must not be sent"); },
  });
  const tree = await openNewAbha(d);
  assert.match(alertText(tree), /government or private/);
  assert.equal(button(tree, "Send OTP").props.disabled, true);
  assert.equal(d.calls.filter((c) => c.name === "requestAbhaEnrolmentOtp").length, 0);
});

test("creating an ABHA requires consent and does not preselect one of several addresses", async () => {
  const d = desk({
    getAbhaEnrolmentDeclaration: async () => DECLARATION,
    requestAbhaLoginOtp: async () => { throw new Error("not this flow"); },
    requestAbhaEnrolmentOtp: async () => ({ session_id: "s1", masked_mobile: null, resends_remaining: 3 }),
    verifyAbhaEnrolmentOtp: async () => ({
      linked: true, linked_patient_id: "patient-A", abha_number: "91-1111-2222-3333",
      session_id: "s1", next_step: "mobile_verify", has_nha_card: true,
    }),
    requestEnrolmentMobileOtp: async () => ({ session_id: "s1", masked_mobile: null, resends_remaining: 3 }),
    verifyEnrolmentMobileOtp: async () => ({
      linked: true, linked_patient_id: "patient-A", abha_number: "91-1111-2222-3333",
      session_id: "s1", next_step: "address_select", suggested_addresses: ["alpha@sbx", "beta@sbx"],
    }),
    submitEnrolmentAbhaAddress: async () => ({
      linked: true, linked_patient_id: "patient-A", abha_number: "91-1111-2222-3333",
      abha_address: "beta@sbx", next_step: "complete", has_nha_card: true,
    }),
    resendAbhaOtp: async () => { throw new Error("unused"); },
    verifyAbhaLoginOtp: async () => { throw new Error("unused"); },
    downloadNhaAbhaCard: async () => { throw new Error("unused"); },
  });
  let tree = await openNewAbha(d);
  assert.equal(button(tree, "Send OTP").props.disabled, true);
  tick(tree, "health_worker"); tree = d.render();
  tick(tree, "beneficiary"); tree = d.render();
  assert.equal(button(tree, "Send OTP").props.disabled, false);
  await button(tree, "Send OTP").props.onClick(); await flush();
  tree = d.render();
  const enrolment = d.calls.find((c) => c.name === "requestAbhaEnrolmentOtp");
  assert.equal(enrolment.args[2].code, "abha-enrollment");
  assert.equal(enrolment.args[2].granted, true);
  nodes(tree).find((n) => n.props?.autoComplete === "one-time-code").props.onChange({ target: { value: "123456" } });
  tree = d.render();
  await button(tree, "Verify and link").props.onClick(); await flush();
  tree = d.render();
  const mobile = nodes(tree).find((n) => n.type === "input" && n.props.inputMode === "tel");
  mobile.props.onChange({ target: { value: "9876543210" } });
  tree = d.render();
  await button(tree, "Send mobile OTP").props.onClick(); await flush();
  nodes(tree).filter((n) => n.type === "input").at(-1).props.onChange({ target: { value: "654321" } });
  tree = d.render();
  await button(tree, "Verify mobile").props.onClick(); await flush();
  tree = d.render();
  const chosen = nodes(tree).filter((n) => n.type === "input" && n.props.type === "radio" && n.props.checked);
  assert.equal(chosen.length, 0, "several suggestions must not preselect the first");
  const beta = nodes(tree).find((n) => n.type === "input" && n.props.value === "beta@sbx");
  beta.props.onChange();
  tree = d.render();
  await button(tree, "Save ABHA address").props.onClick(); await flush();
  tree = d.render();
  assert.match(content(tree), /beta@sbx/);
  assert.match(content(tree), /National Health Authority/);
  assert.equal(d.calls.find((c) => c.name === "submitEnrolmentAbhaAddress").args[2], "beta@sbx");
});

/** M1 CRT_ABHA_301-309: Aadhaar demographic ABHA creation at the desk. */
function demographicDesk(apiStubs, patient) {
  const calls = [];
  const record = (name, impl) => async (...args) => { calls.push({ name, args }); return impl(...args); };
  const api = Object.fromEntries(Object.entries(apiStubs).map(([name, impl]) => [name, record(name, impl)]));
  const h = componentHarness((runtime) => compile(source("AbhaIdentityPanel.tsx"), {
    ...runtime,
    "@/lib/api": { ApiError: TestApiError, newIdempotencyKey: () => "synthetic-key" },
    "./api": api,
    "./patientValidation": compile(source("patientValidation.ts"), {}),
    ...panelParts(runtime, api),
  }).AbhaIdentityPanel);
  const render = () => { const tree = h.render({ patient }); h.effects(); return tree; };
  return { calls, render };
}

const field = (tree, name) => find(tree, (n) => (n.type === "input" || n.type === "select") && n.props.name === name);
const CHART = {
  id: "patient-A", full_name: "Aarav Sharma", abha_number: null, sex: "male", dob: "1990-05-17",
  mobile: "+919876543210", address_line: "12 Synthetic Lane", pincode: "415001",
};

test("demographic creation prefills from the chart, takes LGD codes from the list and binds the result", async () => {
  const d = demographicDesk({
    getAbhaEnrolmentDeclaration: async () => DECLARATION,
    listLgdStates: async () => [{ code: "27", name: "MAHARASHTRA" }],
    listLgdDistricts: async (state) => (state === "27" ? [{ code: "494", name: "SATARA" }] : []),
    enrolAbhaByDemographics: async () => ({
      abha_number: "91-5006-4247-3341", abha_address: "91500642473341@sbx", name: "Aarav Sharma",
      gender: "M", date_of_birth: "17-05-1990", linked_patient_id: "patient-A", linked: true, has_nha_card: true,
    }),
  }, CHART);
  let tree = d.render();
  button(tree, "Create with Aadhaar demographics").props.onClick();
  d.render(); await flush(); tree = d.render();
  assert.equal(field(tree, "name").props.value, "Aarav Sharma");
  assert.equal(field(tree, "date_of_birth").props.value, "1990-05-17");
  assert.equal(field(tree, "gender").props.value, "M");
  assert.equal(field(tree, "mobile").props.value, "9876543210", "stored E.164 becomes ten national digits");
  assert.equal(button(tree, "Create ABHA from these details").props.disabled, true);

  field(tree, "aadhaar").props.onChange({ target: { value: "9999 8888 7777" } }); tree = d.render();
  field(tree, "state_code").props.onChange({ target: { value: "27" } });
  d.render(); await flush(); tree = d.render();
  assert.deepEqual(d.calls.find((c) => c.name === "listLgdDistricts").args, ["27"]);
  field(tree, "district_code").props.onChange({ target: { value: "494" } }); tree = d.render();
  assert.equal(button(tree, "Create ABHA from these details").props.disabled, true, "the consent confirmations are still empty");
  tick(tree, "health_worker"); tree = d.render();
  tick(tree, "beneficiary"); tree = d.render();
  assert.equal(button(tree, "Create ABHA from these details").props.disabled, false);

  await button(tree, "Create ABHA from these details").props.onClick(); await flush();
  const [body, key] = d.calls.find((c) => c.name === "enrolAbhaByDemographics").args;
  assert.equal(key, "synthetic-key");
  assert.deepEqual({ ...body, consent: undefined }, {
    aadhaar: "9999 8888 7777", name: "Aarav Sharma", date_of_birth: "1990-05-17", gender: "M",
    mobile: "9876543210", address: "12 Synthetic Lane", pincode: "415001", state_code: "27",
    district_code: "494", patient_id: "patient-A", consent: undefined,
  });
  assert.equal(body.consent.declaration_sha256, DECLARATION.sha256);
  assert.equal(body.consent.statements.beneficiary, true);
  tree = d.render();
  assert.match(content(tree), /ABHA verified and linked/);
  assert.match(content(tree), /91-5006-4247-3341/);
  assert.doesNotMatch(content(tree), /999988887777|9999 8888 7777/);
});

test("changing the state clears the chosen district", async () => {
  const d = demographicDesk({
    getAbhaEnrolmentDeclaration: async () => DECLARATION,
    listLgdStates: async () => [{ code: "27", name: "MAHARASHTRA" }, { code: "7", name: "DELHI" }],
    listLgdDistricts: async (state) => (state === "27" ? [{ code: "494", name: "SATARA" }] : [{ code: "77", name: "NEW DELHI" }]),
  }, CHART);
  let tree = d.render();
  button(tree, "Create with Aadhaar demographics").props.onClick();
  d.render(); await flush(); tree = d.render();
  field(tree, "state_code").props.onChange({ target: { value: "27" } });
  d.render(); await flush(); tree = d.render();
  field(tree, "district_code").props.onChange({ target: { value: "494" } }); tree = d.render();
  field(tree, "state_code").props.onChange({ target: { value: "7" } }); tree = d.render();
  assert.equal(field(tree, "district_code").props.value, "", "a district of the previous state is not kept");
});

test("an LGD list that cannot be loaded is a refusal, not an empty list", async () => {
  const d = demographicDesk({
    getAbhaEnrolmentDeclaration: async () => DECLARATION,
    listLgdStates: async () => { throw new TestApiError(409, "The LGD state and district list is not loaded on this server", { code: "lgd_reference_unavailable" }); },
    enrolAbhaByDemographics: async () => { throw new Error("must not be sent"); },
  }, CHART);
  let tree = d.render();
  button(tree, "Create with Aadhaar demographics").props.onClick();
  d.render(); await flush(); tree = d.render();
  assert.match(alertText(tree), /LGD state and district list is not loaded/);
  assert.equal(button(tree, "Create ABHA from these details").props.disabled, true);
});


test("switching the consent to Hindi reloads it, shows the translation notice and sends hi", async () => {
  const HINDI = { ...DECLARATION, language: "hi", sha256: "b".repeat(64),
    notice: "हिन्दी अनुवाद HealthDoc द्वारा; NHA का प्रकाशित पाठ अंग्रेज़ी में है।", intro: "मैं एतद्द्वारा घोषणा करता/करती हूँ कि:" };
  const d = desk({
    getAbhaEnrolmentDeclaration: async (_patient, language) => (language === "hi" ? HINDI : DECLARATION),
    requestAbhaEnrolmentOtp: async () => ({ session_id: "s1", masked_mobile: null, resends_remaining: 3 }),
  });
  let tree = await openNewAbha(d);
  tick(tree, "health_worker"); tree = d.render();
  button(tree, "हिन्दी").props.onClick();
  d.render(); await flush(); tree = d.render();
  assert.deepEqual(d.calls.filter((c) => c.name === "getAbhaEnrolmentDeclaration").map((c) => c.args[1]), ["en", "hi"]);
  assert.match(content(tree), /HealthDoc द्वारा/);
  assert.equal(find(tree, (n) => n.type === "input" && n.props.name === "health_worker").props.checked, false,
    "ticks start again for the new text");
  tick(tree, "health_worker"); tree = d.render();
  tick(tree, "beneficiary"); tree = d.render();
  await button(tree, "Send OTP").props.onClick(); await flush();
  const sent = d.calls.find((c) => c.name === "requestAbhaEnrolmentOtp").args[2];
  assert.equal(sent.language, "hi");
  assert.equal(sent.declaration_sha256, HINDI.sha256);
});
