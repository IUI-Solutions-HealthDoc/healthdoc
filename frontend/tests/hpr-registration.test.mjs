import assert from "node:assert/strict";
import test from "node:test";
import { compile, componentHarness, content, flush, nodes } from "./helpers/component-harness.mjs";

/** HPR registration of the signed-in professional (ABDM M4 HPR-018 to 079).
 * Synthetic transport; lists are shaped like HPR's masters as HealthDoc maps them. */
class TestApiError extends Error {
  constructor(code, message, requestId, payload) { super(message); this.code = code; this.payload = payload; }
}
const source = new URL("../src/features/admin/HprProfessionalRegistration.tsx", import.meta.url);
const find = (tree, predicate) => nodes(tree).find(predicate);
const button = (tree, text) => find(tree, (n) => n.type === "button" && content(n).replace(/\s+/g, " ").trim().startsWith(text));
const field = (tree, name) => find(tree, (n) => (n.type === "input" || n.type === "select") && n.props.name === name);
const PROFILE = { hpr_id: "asha.verma@hpr.abdm", hpr_id_number: "71-0000-0000-0002", name: "Asha Kumari Verma",
  first_name: "Asha", middle_name: "Kumari", last_name: "Verma", gender: "F", birth_date: "1990-04-07",
  address: "1 Synthetic Lane, Pune", state_name: "Maharashtra", district_name: "Pune", pincode: "411001",
  email: "asha@example.org", photo: "", mobile_hint: "3210" };
const PDF = { file_type: "pdf", content: "JVBERi0=" };

function form(overrides = {}) {
  const calls = [];
  const stubs = {
    hprProfile: async () => PROFILE,
    hprProfessional: async () => ({ practitioner: null }),
    hprContact: async () => ({ mobile_verified: false, mobile_hint: null, email_verified: false, email: null }),
    hprRegistrationOptions: async () => ({
      salutations: [{ code: "1", label: "Dr." }, { code: "2", label: "Mr." }, { code: "3", label: "Ms." }, { code: "0", label: "Do not specify" }],
      categories: [{ code: "1", label: "Doctor" }, { code: "2", label: "Nurse" }, { code: "6", label: "Pharmacist" }],
      doctor_systems: [{ code: "1", label: "Modern Medicine" }, { code: "2", label: "Dentistry" }],
      nurse_types: [{ code: "8", label: "RANM" }], pharmacist_type: { code: "13", label: "Pharmacist" },
      work_status: [{ code: "PRIVATE", label: "Private only" }, { code: "GOVERNMENT", label: "Government only" }, { code: "BOTH", label: "Both" }],
      government_types: [{ code: "CENTRAL", label: "Central government" }, { code: "STATE", label: "State government" }],
      purposes: ["Administrative", "Practice", "Teaching", "Research"],
      not_working_reasons: ["Retired", "Voluntary Opt-Out", "Suspended"], months: ["January", "February"] }),
    hprSystems: async () => [{ code: "1", label: "Modern Medicine", hpr_type: "doctor" }, { code: "2", label: "Dentistry", hpr_type: "doctor" }],
    hprCouncils: async () => [{ code: "23", label: "Maharashtra Medical Council", state_id: "20", system_of_medicine_id: 1 },
      { code: "99", label: "Dental Council", state_id: "20", system_of_medicine_id: 2 }],
    hprCountries: async () => [{ code: "356", label: "India" }],
    hprLanguages: async () => [{ code: "1", label: "English" }, { code: "2", label: "Hindi" }],
    hprStates: async () => [{ code: "20", label: "Maharashtra" }],
    hprDistricts: async () => [{ code: "499", label: "Washim" }],
    hprSubDistricts: async () => [],
    hprCourses: async () => [{ code: "4060", label: "MBBS" }],
    hprColleges: async () => [{ code: "1022", label: "Synthetic Medical College" }],
    hprUniversities: async () => [{ code: "6372", label: "Synthetic University" }],
    registerHprProfessional: async () => ({ reference_number: "REF1", status: "SUBMITTED", message: "ok", hpr_id: "asha.verma@hpr.abdm", hpr_id_number: "71-0000-0000-0002" }),
    updateHprProfessional: async () => ({ reference_number: null, status: "UPDATED", message: "ok", hpr_id: null, hpr_id_number: null }),
    ...overrides,
  };
  const api = Object.fromEntries(Object.entries(stubs).map(([name, impl]) =>
    [name, async (...args) => { calls.push({ name, args }); return impl(...args); }]));
  const h = componentHarness((runtime) => compile(source, {
    ...runtime,
    "@/lib/api": { ApiError: TestApiError, newIdempotencyKey: () => "synthetic-key" },
    "./api/hpr": api,
    "./hprDocument": { HPR_DOCUMENT_ACCEPT: "application/pdf", readHprDocument: async () => PDF },
    "./HprContactVerifier": { HprContactVerifier: (props) => ({ type: "contact-verifier", props, children: [] }) },
  }).HprProfessionalRegistration);
  let props = { signedIn: true };
  const render = (next) => { if (next) props = next; const tree = h.render(props); h.effects(); return tree; };
  return { calls, render };
}

async function settle(d) { for (let i = 0; i < 3; i += 1) { d.render(); await flush(); } return d.render(); }
const type = (tree, name, value) => field(tree, name).props.onChange({ target: { value } });
const tick = (tree, name, checked = true) => field(tree, name).props.onChange({ target: { checked } });
const attach = async (d, tree, name) => { field(tree, name).props.onChange({ target: { files: [{ name: `${name}.pdf` }] } }); return settle(d); };

async function opened(d) {
  const tree = d.render();
  button(tree, "Open the HPR registration").props.onClick();
  return settle(d);
}

async function fill(d) {
  let tree = await opened(d);
  type(tree, "salutation", "1"); tree = d.render();
  type(tree, "category", "1"); tree = d.render();
  type(tree, "subcategory", "1"); tree = await settle(d);
  tick(tree, "language:1"); tree = d.render();
  type(tree, "father_name", "Ramesh Verma"); tree = d.render();
  type(tree, "council", "23"); tree = d.render();
  type(tree, "reg_number", "MMC-2015-123"); tree = d.render();
  type(tree, "reg_date", "2015-06-01"); tree = d.render();
  tree = await attach(d, tree, "reg_certificate");
  type(tree, "q0_degree", "4060"); tree = d.render();
  type(tree, "q0_state", "20"); tree = await settle(d);
  type(tree, "q0_college", "1022"); tree = await settle(d);
  type(tree, "q0_university", "6372"); tree = d.render();
  type(tree, "q0_year", "2014"); tree = d.render();
  tree = await attach(d, tree, "q0_certificate");
  type(tree, "working", "yes"); tree = d.render();
  type(tree, "work_purpose", "Practice"); tree = d.render();
  type(tree, "work_status", "PRIVATE"); tree = d.render();
  type(tree, "facility_id", "in2710005985"); tree = d.render();
  return tree;
}

test("nothing loads until the professional is signed in and the form is opened", async () => {
  const d = form();
  const tree = d.render({ signedIn: false });
  assert.equal(button(tree, "Open the HPR registration").props.disabled, true);
  await flush();
  assert.deepEqual(d.calls, []);
});

test("Aadhaar's details are shown and no field edits them", async () => {
  const d = form();
  const tree = await opened(d);
  assert.match(content(tree), /Asha Kumari Verma/);
  assert.match(content(tree), /1990-04-07/);
  assert.match(content(tree), /ending 3210/);
  for (const name of ["first_name", "last_name", "gender", "birth_date", "kyc_address"]) {
    assert.equal(field(tree, name), undefined, `${name} is not an input`);
  }
  assert.deepEqual(nodes(field(tree, "salutation")).filter((n) => n.type === "option").map((n) => content(n).trim()),
    ["Choose", "Dr.", "Mr.", "Ms.", "Do not specify"], "NHA's salutations only");
});

test("the filled form registers with HPR's codes and the KYC stays server-side", async () => {
  const d = form();
  let tree = await fill(d);
  assert.deepEqual(nodes(field(tree, "council")).filter((n) => n.type === "option").map((n) => n.props.value), ["", "23"],
    "only the councils for the chosen system of medicine");
  assert.deepEqual(d.calls.find((c) => c.name === "hprCourses").args, ["Modern Medicine", "doctor"]);
  assert.deepEqual(d.calls.find((c) => c.name === "hprColleges").args, ["20", "Modern Medicine"]);
  assert.equal(button(tree, "Submit to HPR").props.disabled, false);
  await button(tree, "Submit to HPR").props.onClick(); tree = await settle(d);
  const [body, key] = d.calls.find((c) => c.name === "registerHprProfessional").args;
  assert.equal(key, "synthetic-key");
  assert.equal("first_name" in body, false, "Aadhaar's names are not sent from the browser");
  assert.deepEqual([body.salutation, body.category, body.subcategory, body.languages], [1, 1, 1, [1]]);
  assert.equal(body.communication_address, null, "same as the KYC address");
  assert.deepEqual(body.registration.certificate, PDF);
  assert.deepEqual(body.registration.qualifications[0], { degree: 4060, country: "356", state: "20", college: 1022,
    university: 6372, year: 2014, month: null, certificate: PDF, name_differs: false, name_change_proof: null });
  assert.deepEqual(body.work, { working: true, reason_not_working: "", purpose: "Practice", status: "PRIVATE",
    government_type: null, ministry: "", proof: null, facility_id: "IN2710005985", department: "", designation: "" });
  assert.match(content(tree), /Submitted in HPR, reference REF1/);
});

test("government work needs central or state, a ministry for central, and proof (HPR-074/075)", async () => {
  const d = form();
  let tree = await fill(d);
  type(tree, "work_status", "GOVERNMENT"); tree = d.render();
  assert.equal(button(tree, "Submit to HPR").props.disabled, true);
  tree = await attach(d, tree, "work_proof");
  assert.equal(button(tree, "Submit to HPR").props.disabled, true, "central or state still to choose");
  type(tree, "government_type", "CENTRAL"); tree = d.render();
  assert.equal(button(tree, "Submit to HPR").props.disabled, true, "central work names its ministry");
  type(tree, "ministry", "MinistryMOR ( Mo Railways )"); tree = d.render();
  assert.equal(button(tree, "Submit to HPR").props.disabled, false);
  await button(tree, "Submit to HPR").props.onClick(); tree = await settle(d);
  const [body] = d.calls.find((c) => c.name === "registerHprProfessional").args;
  assert.equal(body.work.government_type, "CENTRAL");
  assert.equal(body.work.ministry, "MinistryMOR ( Mo Railways )");
});

test("a login without Aadhaar details is sent to verify Aadhaar first", async () => {
  const d = form({ hprProfile: async () => {
    throw new TestApiError(409, "kyc", undefined, { code: "hpr_kyc_required", message: "Verify" });
  } });
  const tree = await opened(d);
  assert.match(content(tree), /carries no Aadhaar details/);
  assert.match(content(tree), /Verify Aadhaar on NHA/);
  assert.equal(button(tree, "Submit to HPR"), undefined);
});

test("a professional HPR already holds is updated, not registered again (HPR-079)", async () => {
  const d = form({ hprProfessional: async () => ({ practitioner: { application_status: "PENDING" } }) });
  let tree = await fill(d);
  assert.match(content(tree), /already holds a registration/);
  assert.equal(button(tree, "Submit to HPR"), undefined);
  await button(tree, "Update in HPR").props.onClick(); tree = await settle(d);
  assert.equal(d.calls.some((c) => c.name === "registerHprProfessional"), false);
  assert.equal(d.calls.some((c) => c.name === "updateHprProfessional"), true);
  assert.match(content(tree), /Updated in HPR/);
});

test("HPR's own refusal is shown", async () => {
  const d = form({ registerHprProfessional: async () => {
    throw new TestApiError(400, "refused", undefined, { code: "hpr_registration_refused", messages: ["Registration number already exists"] });
  } });
  let tree = await fill(d);
  await button(tree, "Submit to HPR").props.onClick(); tree = await settle(d);
  assert.match(content(tree), /Registration number already exists/);
});
