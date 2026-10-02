import assert from "node:assert/strict";
import test from "node:test";
import { compile, componentHarness, content, flush, nodes } from "./helpers/component-harness.mjs";

/** HFR facility registration (ABDM M4 HFR-010 to 117). Synthetic transport;
 * every list and answer below is a stub shaped like HFR's. */
class TestApiError extends Error {
  constructor(code, message, requestId, payload) { super(message); this.code = code; this.payload = payload; }
}
const source = (path) => new URL(`../src/features/admin/${path}`, import.meta.url);
const find = (tree, predicate) => nodes(tree).find(predicate);
const button = (tree, text) => find(tree, (n) => n.type === "button" && content(n).replace(/\s+/g, " ").trim().startsWith(text));
const field = (tree, name) => find(tree, (n) => (n.type === "input" || n.type === "select") && n.props.name === name);
const alerts = (tree) => nodes(tree).filter((n) => n.props?.role === "alert").map(content).join(" ");

const MASTERS = {
  OWNER: [{ code: "G         ", value: "Government" }, { code: "P         ", value: "Private" }],
  MEDICINE: [{ code: "M", value: "Modern Medicine(Allopathy)" }],
  "TYPE-SERVICE": [{ code: "OPD", value: "OPD" }, { code: "IPD", value: "IPD" }],
  "FACILITY-REGION": [{ code: "U", value: "Urban" }],
  "SPECIALITY-TYPE": [{ code: "MULTI", value: "Multi Speciality" }],
  "FAC-STATUS": [{ code: "F", value: "Functional" }],
  "DAYS-OF-OPERATION": [{ code: "Mon", value: "Mon" }, { code: "Tue", value: "Tue" }],
  "ADDRESS-PROOF": [{ code: "EBill", value: "Electricity Bill" }],
  "GENERAL-INFO-OPTIONS": [{ code: "YALL", value: "Yes, for everyone" }, { code: "N", value: "No" }],
  IMAGING: [{ code: "S136", value: "X-Ray" }],
  DIAGNOSTIC: [{ code: "S212", value: "Pathology" }],
};

function registration(overrides = {}) {
  const calls = [];
  const stubs = {
    hfrMaster: async (kind) => MASTERS[kind],
    hfrStates: async () => [{ code: "27", name: "Maharashtra" }],
    hfrDistricts: async () => [{ code: "490", name: "Pune" }],
    hfrSubdistricts: async () => [{ code: "4194", name: "Pune City" }],
    hfrOwnerSubtypes: async () => [{ code: "PP02", value: "Registered companies" }],
    hfrFacilityTypes: async () => [{ code: "40", value: "Hospital" }],
    hfrFacilitySubtypes: async () => [{ code: "28", value: "General Hospital" }],
    hfrSpecialities: async () => [{ code: "M-S1", value: "GeneralMedicine" }],
    saveHfrBasic: async () => ({ tracking_id: "98060", status: "success", message: "saved" }),
    saveHfrAdditional: async () => ({ tracking_id: "98060", status: "Created", message: "saved" }),
    saveHfrDetailed: async () => ({ tracking_id: "98060", status: "Saved", message: "saved" }),
    submitHfrFacility: async () => ({ facility_id: "IN2710005985", status: "Created", message: "Facility created successfully." }),
    ...overrides,
  };
  const api = Object.fromEntries(Object.entries(stubs).map(([name, impl]) =>
    [name, async (...args) => { calls.push({ name, args }); return impl(...args); }]));
  const h = componentHarness((runtime) => compile(source("HfrRegistration.tsx"), {
    ...runtime,
    "@/lib/api": { ApiError: TestApiError, newIdempotencyKey: () => "synthetic-key" },
    "./api/hfr": api,
    "./hfrUpload": { readHfrUpload: async (file) => ({ name: file.name, content: `base64-of-${file.name}` }) },
  }).HfrRegistration);
  let props = { signedIn: true };
  const render = (next) => { if (next) props = next; const tree = h.render(props); h.effects(); return tree; };
  return { calls, render };
}

async function settle(d) { d.render(); await flush(); d.render(); await flush(); return d.render(); }
const type = (tree, name, value) => field(tree, name).props.onChange({ target: { value } });
const tick = (tree, name, checked = true) => field(tree, name).props.onChange({ target: { checked } });

async function fillBasic(d) {
  let tree = d.render();
  button(tree, "Start registration").props.onClick();
  tree = await settle(d);
  type(tree, "facility_name", "HealthDoc Sandbox Test Hospital"); tree = d.render();
  type(tree, "state", "27"); tree = await settle(d);
  type(tree, "district", "490"); tree = await settle(d);
  type(tree, "subdistrict", "4194"); tree = d.render();
  type(tree, "region", "U"); tree = d.render();
  type(tree, "address_line1", "Synthetic Test Block, 1 Test Road"); tree = d.render();
  type(tree, "pincode", "411001"); tree = d.render();
  type(tree, "latitude", "18.520430"); tree = d.render();
  type(tree, "longitude", "73.856743"); tree = d.render();
  type(tree, "email", "hfr-test@example.org"); tree = d.render();
  type(tree, "mobile", "7078594541"); tree = d.render();
  type(tree, "ownership", "P"); tree = await settle(d);
  type(tree, "ownership_subtype2", "PP02"); tree = d.render();
  tick(tree, "medicine:M"); tree = await settle(d);
  type(tree, "facility_type", "40"); tree = await settle(d);
  type(tree, "facility_subtype", "28"); tree = d.render();
  tick(tree, "service:OPD"); tree = d.render();
  type(tree, "speciality_type", "MULTI"); tree = d.render();
  type(tree, "operational_status", "F"); tree = d.render();
  tick(tree, "days0:Mon"); tree = d.render();
  type(tree, "hours0", "9:00 AM - 6:00 PM"); tree = d.render();
  for (const name of ["board_photo", "building_photo"]) {
    await field(tree, name).props.onChange({ target: { files: [{ name: `${name}.png` }] } });
    tree = await settle(d);
  }
  return tree;
}

test("nothing is asked of HFR until registration starts, and only when signed in to HPR", async () => {
  const d = registration();
  let tree = d.render({ signedIn: false });
  assert.equal(button(tree, "Start registration").props.disabled, true);
  assert.match(content(tree), /Sign in to HPR above first/);
  tree = d.render({ signedIn: true });
  await flush();
  assert.deepEqual(d.calls, [], "the page alone asks HFR for nothing");
});

test("the four steps carry one tracking id and end with HFR's facility id", async () => {
  const d = registration();
  let tree = await fillBasic(d);
  assert.equal(field(tree, "ownership_subtype").props.value, "P", "private starts at for profit");
  assert.deepEqual(d.calls.find((c) => c.name === "hfrOwnerSubtypes").args, ["P", "P"]);
  assert.deepEqual(d.calls.find((c) => c.name === "hfrFacilityTypes").args, ["P", "M"], "HFR's padded owner code is trimmed");
  assert.equal(button(tree, "Save basic information").props.disabled, false);

  await button(tree, "Save basic information").props.onClick(); await flush();
  const [basic, key] = d.calls.find((c) => c.name === "saveHfrBasic").args;
  assert.equal(key, "synthetic-key");
  assert.equal(basic.name, "HealthDoc Sandbox Test Hospital");
  assert.deepEqual(basic.address, {
    state_code: "27", district_code: "490", sub_district_code: "4194", region: "U",
    address_line1: "Synthetic Test Block, 1 Test Road", address_line2: "", pincode: "411001",
    latitude: "18.520430", longitude: "73.856743",
  });
  assert.deepEqual([basic.ownership_code, basic.ownership_subtype_code, basic.ownership_subtype_code2], ["P", "P", "PP02"]);
  assert.deepEqual(basic.timings, [{ days: ["Mon"], hours: "9:00 AM - 6:00 PM" }]);
  assert.deepEqual(basic.board_photo, { name: "board_photo.png", content: "base64-of-board_photo.png" });
  tree = await settle(d);
  assert.match(content(tree), /Tracking ID 98060/);

  type(tree, "pharmacy", "YALL"); tree = d.render();
  await button(tree, "Save additional information").props.onClick(); await flush();
  const [additional] = d.calls.find((c) => c.name === "saveHfrAdditional").args;
  assert.equal(additional.tracking_id, "98060");
  assert.equal(additional.general.pharmacy, "YALL");
  assert.deepEqual(additional.imaging_services, []);
  tree = await settle(d);

  tick(tree, "specialisation:M"); tree = await settle(d);
  tick(tree, "speciality:M:M-S1"); tree = d.render();
  type(tree, "ipd_beds_without_oxygen", "10"); tree = d.render();
  type(tree, "hdu_beds_with_ventilators", "2"); tree = d.render();
  type(tree, "icu_beds_with_ventilators", "3"); tree = d.render();
  assert.match(content(tree), /Total beds \(IPD and HDU\):\s*12/);
  assert.match(content(tree), /Total ventilators:\s*5/);
  await button(tree, "Save detailed information").props.onClick(); await flush();
  const [detailed] = d.calls.find((c) => c.name === "saveHfrDetailed").args;
  assert.deepEqual(detailed.specialities, [{ system_of_medicine: "M", available: "Y", codes: ["M-S1"] }]);
  assert.equal(detailed.infrastructure.ipd_beds_without_oxygen, 10);
  assert.deepEqual(detailed.imaging_services, []);
  tree = await settle(d);

  await button(tree, "Submit to HFR").props.onClick(); await flush();
  assert.deepEqual(d.calls.find((c) => c.name === "submitHfrFacility").args, ["98060", "synthetic-key"]);
  tree = await settle(d);
  assert.match(content(tree), /IN2710005985/);
});

test("HFR's own field messages are shown and the form stays to be corrected", async () => {
  const d = registration({
    saveHfrBasic: async () => {
      throw new TestApiError(400, "HFR refused", undefined, {
        code: "hfr_registration_refused", messages: ["Please enter Facility Board Photo Name"] });
    },
  });
  let tree = await fillBasic(d);
  await button(tree, "Save basic information").props.onClick(); await flush();
  tree = await settle(d);
  assert.match(alerts(tree), /Please enter Facility Board Photo Name/);
  assert.equal(field(tree, "facility_name").props.value, "HealthDoc Sandbox Test Hospital");
});

test("save stays disabled until the workbook's rules hold", async () => {
  const d = registration();
  let tree = await fillBasic(d);
  type(tree, "facility_name", "1st Hospital"); tree = d.render();
  assert.equal(button(tree, "Save basic information").props.disabled, true);
  type(tree, "facility_name", "Good Hospital"); tree = d.render();
  type(tree, "hours0", "nine to five"); tree = d.render();
  assert.equal(button(tree, "Save basic information").props.disabled, true);
  type(tree, "hours0", "24*7"); tree = d.render();
  assert.equal(button(tree, "Save basic information").props.disabled, false);
});
