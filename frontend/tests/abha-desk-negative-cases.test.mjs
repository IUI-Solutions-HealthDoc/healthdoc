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

function desk(apiStubs) {
  const calls = [];
  const record = (name, impl) => async (...args) => { calls.push({ name, args }); return impl(...args); };
  const api = Object.fromEntries(Object.entries(apiStubs).map(([name, impl]) => [name, record(name, impl)]));
  const h = componentHarness((runtime) => compile(source("AbhaIdentityPanel.tsx"), {
    ...runtime,
    "@/lib/api": { ApiError: TestApiError, newIdempotencyKey: () => "synthetic-key" },
    "./api": api,
    "./patientValidation": compile(source("patientValidation.ts"), {}),
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
  }).AbhaIdentityPanel);
  const other = h.render({ patient: { id: "patient-B", full_name: "Other Patient", abha_number: null } }); h.effects();
  assert.equal(button(other, "Resend OTP"), undefined);
  assert.ok(button(other, "Send OTP"), "a new patient starts from the identifier step");
  assert.doesNotMatch(content(other), /999988887777/);
});

test("creating an ABHA requires consent and does not preselect one of several addresses", async () => {
  const d = desk({
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
  let tree = d.render();
  button(tree, "Create ABHA").props.onClick();
  tree = d.render();
  input(tree).props.onChange({ target: { value: "999988887777" } });
  tree = d.render();
  assert.equal(button(tree, "Send OTP").props.disabled, true);
  const consent = find(tree, (n) => n.type === "input" && n.props.type === "checkbox");
  consent.props.onChange({ target: { checked: true } });
  tree = d.render();
  assert.equal(button(tree, "Send OTP").props.disabled, false);
  await button(tree, "Send OTP").props.onClick(); await flush();
  tree = d.render();
  assert.equal(d.calls[0].args[2].code, "abha-enrollment");
  assert.equal(d.calls[0].args[2].granted, true);
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
