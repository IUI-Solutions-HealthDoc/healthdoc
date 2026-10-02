import assert from "node:assert/strict";
import test from "node:test";
import { compile, componentHarness, content, flush, nodes } from "./helpers/component-harness.mjs";

/** ABDM M4 HFR admin screen: search (HFR-001 to 009) and bridge linkage
 * (HFR-118 to 123). Synthetic transport; nothing leaves this process. */

class TestApiError extends Error {
  constructor(code, message) { super(message); this.code = code; }
}
const source = new URL("../src/features/admin/HfrFacilityRegistry.tsx", import.meta.url);
const find = (tree, predicate) => nodes(tree).find(predicate);
const button = (tree, text) => find(tree, (n) => n.type === "button" && content(n).replace(/\s+/g, " ").trim().startsWith(text));
const field = (tree, name) => find(tree, (n) => (n.type === "input" || n.type === "select") && n.props.name === name);
const alerts = (tree) => nodes(tree).filter((n) => n.props?.role === "alert").map(content).join(" ");

function screen(stubs) {
  const calls = [];
  const record = (name, impl) => async (...args) => { calls.push({ name, args }); return impl(...args); };
  const api = Object.fromEntries(Object.entries({
    hfrMaster: async () => [{ code: "G", value: "Government" }, { code: "P", value: "Private" }],
    hfrStates: async () => [{ code: "27", name: "Maharashtra" }],
    hfrDistricts: async () => [{ code: "494", name: "Satara" }],
    hfrSubdistricts: async () => [{ code: "4100", name: "Satara Rural" }],
    searchHfr: async () => ({ facilities: [], page: 1, results_per_page: 10, total: 0, pages: 0 }),
    linkHfrBridge: async () => { throw new Error("unused"); },
    ...stubs,
  }).map(([name, impl]) => [name, record(name, impl)]));
  const h = componentHarness((runtime) => compile(source, {
    ...runtime,
    "@/lib/api": { ApiError: TestApiError, newIdempotencyKey: () => "synthetic-key" },
    "./api/hfr": api,
  }).HfrFacilityRegistry);
  const render = () => { const tree = h.render({}); h.effects(); return tree; };
  return { calls, render };
}

const FOUND = {
  facilities: [{ facilityId: "IN0910034387", facilityName: "HealthDoc Facility", facilityStatus: "Submitted", stateName: "Uttar Pradesh" }],
  page: 1, results_per_page: 10, total: 1, pages: 1,
};

test("a facility id search needs a valid id and sends nothing else", async () => {
  const d = screen({ searchHfr: async () => FOUND });
  let tree = d.render(); await flush(); tree = d.render();
  field(tree, "facility_id").props.onChange({ target: { value: "in09100343" } }); tree = d.render();
  assert.equal(button(tree, "Search HFR").props.disabled, true);
  assert.match(alerts(tree), /12 characters and starts with IN/);
  field(tree, "facility_id").props.onChange({ target: { value: "in0910034387" } }); tree = d.render();
  assert.equal(field(tree, "facility_id").props.value, "IN0910034387", "upper-cased as typed");
  await button(tree, "Search HFR").props.onClick(); await flush(); tree = d.render();
  assert.deepEqual(d.calls.find((c) => c.name === "searchHfr").args[0], { facility_id: "IN0910034387", page: 1 });
  assert.match(content(tree), /IN0910034387\s+·\s+HealthDoc Facility/);
});

test("nothing calls HFR until name search is opened", async () => {
  const d = screen({});
  let tree = d.render(); await flush(); tree = d.render();
  assert.deepEqual(d.calls, []);
  button(tree, "Search by name").props.onClick();
  d.render(); await flush(); tree = d.render();
  assert.deepEqual(d.calls.map((c) => c.name).sort(), ["hfrMaster", "hfrStates"]);
});

test("a name search needs ownership and state, and the lists come from HFR", async () => {
  const d = screen({ searchHfr: async () => FOUND });
  let tree = d.render(); await flush(); tree = d.render();
  button(tree, "Search by name").props.onClick();
  d.render(); await flush(); tree = d.render();
  assert.equal(nodes(field(tree, "ownership_code")).filter((n) => n.type === "option").length, 3);
  field(tree, "facility_name").props.onChange({ target: { value: "District" } }); tree = d.render();
  assert.equal(button(tree, "Search HFR").props.disabled, true, "ownership and state are still missing");
  field(tree, "ownership_code").props.onChange({ target: { value: "G" } }); tree = d.render();
  field(tree, "state_lgd_code").props.onChange({ target: { value: "27" } });
  d.render(); await flush(); tree = d.render();
  assert.deepEqual(d.calls.find((c) => c.name === "hfrDistricts").args, ["27"]);
  assert.equal(button(tree, "Search HFR").props.disabled, false);
  await button(tree, "Search HFR").props.onClick(); await flush();
  assert.deepEqual(d.calls.find((c) => c.name === "searchHfr").args[0], {
    facility_name: "District", ownership_code: "G", state_lgd_code: "27", page: 1,
  });
});

test("a list HFR cannot load is a refusal, not an empty dropdown", async () => {
  const d = screen({ hfrStates: async () => { throw new TestApiError(502, "HFR refused this client. NHA assigns the HFR role."); } });
  let tree = d.render(); await flush(); tree = d.render();
  button(tree, "Search by name").props.onClick();
  d.render(); await flush(); tree = d.render();
  assert.match(alerts(tree), /NHA assigns the HFR role/);
});

test("bridge linkage sends the chosen services with their PHR names", async () => {
  const d = screen({
    searchHfr: async () => FOUND,
    linkHfrBridge: async (facilityId) => ({ facility_id: facilityId, facility_name: "HealthDoc Facility", bridge_id: "SBXID_053401" }),
  });
  let tree = d.render(); await flush(); tree = d.render();
  field(tree, "facility_id").props.onChange({ target: { value: "IN0910034387" } }); tree = d.render();
  await button(tree, "Search HFR").props.onClick(); await flush(); tree = d.render();
  button(tree, "Link to HealthDoc bridge").props.onClick(); tree = d.render();
  assert.equal(field(tree, "HIP-name").props.value, "HealthDoc Facility", "defaults to the HFR name");
  field(tree, "HIU-include").props.onChange({ target: { checked: true } }); tree = d.render();
  await button(tree, "Link bridge").props.onClick(); await flush(); tree = d.render();
  const [facilityId, services, key] = d.calls.find((c) => c.name === "linkHfrBridge").args;
  assert.equal(facilityId, "IN0910034387");
  assert.equal(key, "synthetic-key");
  assert.deepEqual(services, [
    { type: "HIP", hip_name: "HealthDoc Facility", active: true },
    { type: "HIU", hip_name: "HealthDoc Facility HIU", active: true },
  ]);
  assert.match(content(tree), /linked to bridge SBXID_053401/);
});
