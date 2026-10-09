import assert from "node:assert/strict";
import test from "node:test";
import { compile, componentHarness, content, flush, nodes } from "./helpers/component-harness.mjs";

/** M1 CRT_ABHA_401-411 at the desk: driving-licence enrolment. Synthetic
 * transport and photos; no gateway, OTP, mobile or licence leaves this process. */

class TestApiError extends Error {
  constructor(code, message) { super(message); this.code = code; }
}
const source = (path) => new URL(`../src/features/receptionist/${path}`, import.meta.url);
const find = (tree, predicate) => nodes(tree).find(predicate);
const button = (tree, text) => find(tree, (n) => n.type === "button" && content(n).replace(/\s+/g, " ").trim().startsWith(text));
const field = (tree, name) => find(tree, (n) => (n.type === "input" || n.type === "select") && n.props.name === name);
const tick = (tree, id, checked = true) => field(tree, id).props.onChange({ target: { checked } });
const type = (tree, name, value) => field(tree, name).props.onChange({ target: { value } });

const DOCUMENT_DECLARATION = {
  version: "nha-consent-language-1", ownership: "government", language: "en", method: "document",
  notice: null, intro: "I hereby declare that:", sha256: "d".repeat(64),
  statements: [
    { id: "aadhaar_sharing", text: "I am voluntarily sharing my Aadhaar Number", ticked: false, required: false },
    { id: "other_document", text: "using document other than Aadhaar.", ticked: true, required: true },
    { id: "link_records", text: "linking of my legacy (past) government health records", ticked: true, required: null },
    { id: "share_for_care", text: "I authorize the sharing of all my health records", ticked: true, required: null },
    { id: "anonymised_use", text: "anonymization and subsequent use of my government health records", ticked: true, required: null },
    { id: "health_worker", text: "I, Synthetic Receptionist, confirm", ticked: false, required: true },
    { id: "beneficiary", text: "I, Aarav Kumar Sharma, have been explained", ticked: false, required: true },
  ],
};
const CHART = {
  id: "patient-A", full_name: "Aarav Kumar Sharma", sex: "male", dob: "1990-05-17",
  mobile: "+919876543210", address_line: "12 Synthetic Lane", pincode: "415001",
};

function licenceDesk(overrides = {}) {
  const calls = [];
  const stubs = {
    getAbhaEnrolmentDeclaration: async () => DOCUMENT_DECLARATION,
    listLgdStates: async () => [{ code: "27", name: "MAHARASHTRA" }],
    listLgdDistricts: async () => [{ code: "494", name: "SATARA" }],
    requestLicenceEnrolmentOtp: async () => ({ session_id: "session-1", masked_mobile: "OTP sent to ******3210", resends_remaining: 3 }),
    resendLicenceEnrolmentOtp: async () => ({ session_id: "session-1", masked_mobile: "OTP sent", resends_remaining: 2 }),
    verifyLicenceEnrolmentOtp: async () => undefined,
    enrolByDrivingLicence: async () => ({
      enrolment_number: "91-6483-6362-1216", enrolment_state: "PROVISIONAL",
      abha_address: "91648363621216@sbx", is_new: true, linked: false,
    }),
    ...overrides,
  };
  const api = Object.fromEntries(Object.entries(stubs).map(([name, impl]) =>
    [name, async (...args) => { calls.push({ name, args }); return impl(...args); }]));
  const h = componentHarness((runtime) => {
    const consent = compile(source("AbhaConsentDeclaration.tsx"), runtime);
    return compile(source("DrivingLicenceAbhaEnrolment.tsx"), {
      ...runtime,
      "@/lib/api": { ApiError: TestApiError, newIdempotencyKey: () => "synthetic-key" },
      "./AbhaConsentDeclaration": consent,
      "./api": api,
      "./licencePhoto": { prepareLicencePhoto: async (file) => `photo-of-${file.name}` },
      "./patientValidation": compile(source("patientValidation.ts"), {}),
    }).DrivingLicenceAbhaEnrolment;
  });
  const render = () => { const tree = h.render({ patient: CHART }); h.effects(); return tree; };
  return { calls, render };
}

async function toDetails(d) {
  let tree = d.render(); await flush(); tree = d.render();
  tick(tree, "health_worker"); tree = d.render();
  tick(tree, "beneficiary"); tree = d.render();
  await button(tree, "Send OTP").props.onClick(); await flush();
  tree = d.render();
  type(tree, "licence_otp", "123456"); tree = d.render();
  await button(tree, "Verify OTP").props.onClick(); await flush();
  d.render(); await flush();
  return d.render();
}

async function fillDetails(d, tree) {
  type(tree, "licence_number", "MH12 20110012345"); tree = d.render();
  type(tree, "state_code", "27"); d.render(); await flush(); tree = d.render();
  type(tree, "district_code", "494"); tree = d.render();
  for (const side of ["front", "back"]) {
    await field(tree, `licence_${side}`).props.onChange({ target: { files: [{ name: side, type: "image/jpeg" }] } });
    await flush(); tree = d.render();
  }
  return tree;
}

test("the desk sends the document consent and the mobile, never an Aadhaar statement", async () => {
  const d = licenceDesk();
  let tree = d.render(); await flush(); tree = d.render();
  assert.equal(field(tree, "aadhaar_sharing").props.checked, false);
  assert.equal(field(tree, "other_document").props.checked, true);
  assert.equal(field(tree, "licence_mobile").props.value, "9876543210");
  assert.equal(button(tree, "Send OTP").props.disabled, true, "the confirmations are still empty");
  tick(tree, "health_worker"); tree = d.render();
  tick(tree, "beneficiary"); tree = d.render();
  tick(tree, "aadhaar_sharing"); tree = d.render();
  assert.equal(button(tree, "Send OTP").props.disabled, true, "Aadhaar ticked is not a licence enrolment");
  tick(tree, "aadhaar_sharing", false); tree = d.render();
  await button(tree, "Send OTP").props.onClick(); await flush();
  const [patientId, mobile, consent] = d.calls.find((c) => c.name === "requestLicenceEnrolmentOtp").args;
  assert.deepEqual([patientId, mobile], ["patient-A", "9876543210"]);
  assert.equal(consent.declaration_sha256, DOCUMENT_DECLARATION.sha256);
  assert.equal(consent.statements.other_document, true);
  assert.equal(consent.statements.aadhaar_sharing, false);
  assert.deepEqual(d.calls.find((c) => c.name === "getAbhaEnrolmentDeclaration").args, ["patient-A", "en", "document"]);
});

test("approval needs every field, both photos and the operator's check; the result is not an ABHA", async () => {
  const d = licenceDesk();
  let tree = await toDetails(d);
  assert.equal(field(tree, "first_name").props.value, "Aarav");
  assert.equal(field(tree, "middle_name").props.value, "Kumar");
  assert.equal(field(tree, "last_name").props.value, "Sharma");
  tree = await fillDetails(d, tree);
  assert.equal(button(tree, "Approve and send for enrolment").props.disabled, true, "the operator has not checked it");
  tick(tree, "operator_verified"); tree = d.render();
  assert.equal(button(tree, "Approve and send for enrolment").props.disabled, false);
  type(tree, "pincode", "415002"); tree = d.render();
  assert.equal(field(tree, "operator_verified").props.checked, false, "a changed detail needs a fresh check");
  tick(tree, "operator_verified"); tree = d.render();

  await button(tree, "Approve and send for enrolment").props.onClick(); await flush();
  const [body, key] = d.calls.find((c) => c.name === "enrolByDrivingLicence").args;
  assert.equal(key, "synthetic-key");
  assert.deepEqual(body, {
    licence_number: "MH12 20110012345", first_name: "Aarav", middle_name: "Kumar", last_name: "Sharma",
    date_of_birth: "1990-05-17", gender: "M", address: "12 Synthetic Lane", pincode: "415002",
    state_code: "27", district_code: "494", session_id: "session-1", patient_id: "patient-A",
    front_photo: "photo-of-front", back_photo: "photo-of-back", operator_verified: true,
  });
  tree = d.render();
  assert.match(content(tree), /91-6483-6362-1216/);
  assert.match(content(tree), /not yet an ABHA number/);
  assert.match(content(tree), /not linked to this chart/);
});

test("rejecting the licence sends nothing and starts again from the consent", async () => {
  const d = licenceDesk();
  let tree = await fillDetails(d, await toDetails(d));
  button(tree, "Reject licence").props.onClick();
  tree = d.render();
  assert.match(content(tree), /Licence rejected\. Nothing was sent to ABDM\./);
  assert.ok(button(tree, "Send OTP"), "back at the consent and mobile step");
  assert.equal(d.calls.some((c) => c.name === "enrolByDrivingLicence"), false);
  assert.equal(field(tree, "health_worker").props.checked, false, "the confirmations start again");
});

test("a refusal from ABDM is shown and the details stay for correction", async () => {
  const d = licenceDesk({
    enrolByDrivingLicence: async () => { throw new TestApiError("abha_licence_rejected", "ABDM did not match these details to the driving licence."); },
  });
  let tree = await fillDetails(d, await toDetails(d));
  tick(tree, "operator_verified"); tree = d.render();
  await button(tree, "Approve and send for enrolment").props.onClick(); await flush();
  tree = d.render();
  assert.match(content(tree), /did not match these details/);
  assert.equal(field(tree, "licence_number").props.value, "MH12 20110012345");
});
