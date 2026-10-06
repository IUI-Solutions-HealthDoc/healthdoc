import assert from "node:assert/strict";
import test from "node:test";
import { compile, componentHarness, content, flush, nodes } from "./helpers/component-harness.mjs";

/** A superadmin onboards a facility: create, set its HFR id, first admin, copy setup. Synthetic transport. */
const source = new URL("../src/features/platform/FacilityOnboarding.tsx", import.meta.url);
const FIRST = { id: "f-1", code: "DEV001", name: "First Hospital", state_code: "MH", district: null,
  facility_type: null, hfr_facility_id: "IN0910034387", timezone: "Asia/Kolkata", is_active: true };
const SECOND = { ...FIRST, id: "f-2", code: "DEV002", name: "Second Hospital", state_code: "BR", hfr_facility_id: null };
const find = (tree, predicate) => nodes(tree).find(predicate);
const button = (tree, text) => find(tree, (n) => n.type === "button" && content(n).trim() === text);
const labelled = (tree, label) => find(tree, (n) => (n.type === "input" || n.type === "select") && n.props["aria-label"] === label);

function panel(facilities = [FIRST, SECOND]) {
  const calls = [];
  let changed = 0;
  const api = {
    createPlatformFacility: async (body) => { calls.push(["create", body]); return { ...SECOND, ...body, id: "f-3" }; },
    updatePlatformFacility: async (id, body) => { calls.push(["update", id, body]); return SECOND; },
    createPlatformFacilityAdmin: async (id, body) => { calls.push(["admin", id, body]); return { id: "u-1", username: body.username }; },
    copyPlatformFacilitySetup: async (id, from) => {
      calls.push(["copy", id, from]); return { departments: 42, rooms: 3, wards: 1, stock_locations: 2, tariff_rows: 23 };
    },
  };
  const h = componentHarness((runtime) => compile(source, {
    ...runtime, "@/lib/api": { getUserFacingError: (_r, fallback) => fallback }, "./api": api,
  }).FacilityOnboarding);
  const render = () => { const tree = h.render({ facilities, onChanged: () => { changed += 1; } }); h.effects(); return tree; };
  return { calls, render, changed: () => changed };
}
async function settle(d) { for (let i = 0; i < 3; i += 1) { d.render(); await flush(); } return d.render(); }
const type = (tree, label, value) => labelled(tree, label).props.onChange({ target: { value } });

test("a facility is created only with a valid code, state and HFR id", async () => {
  const d = panel();
  let tree = d.render();
  assert.equal(button(tree, "Create facility").props.disabled, true);
  type(tree, "Code", "DEV002"); type(tree, "Name", "Second Hospital"); type(tree, "State code", "br");
  type(tree, "HFR facility id", "2710009999"); tree = await settle(d);
  assert.equal(button(tree, "Create facility").props.disabled, true, "an HFR id must look like IN0910034387");
  type(tree, "HFR facility id", "IN2710009999"); tree = await settle(d);
  await button(tree, "Create facility").props.onClick(); tree = await settle(d);
  assert.deepEqual(d.calls[0], ["create", { code: "DEV002", name: "Second Hospital", state_code: "BR",
    ownership: null, hfr_facility_id: "IN2710009999" }]);
  assert.match(content(tree), /Second Hospital created/);
  assert.equal(d.changed(), 1);
});

test("the chosen facility gets its HFR id, first admin and another facility's setup", async () => {
  const d = panel();
  let tree = d.render();
  type(tree, "Facility to set up", "f-2"); tree = await settle(d);
  type(tree, "Set HFR facility id", "IN2710005985"); tree = await settle(d);
  await button(tree, "Save HFR id").props.onClick(); tree = await settle(d);
  type(tree, "Admin username", "dev2.admin"); type(tree, "Admin full name", "Second Admin");
  type(tree, "Temporary password", "Synthetic#Pass1"); tree = await settle(d);
  await button(tree, "Create first admin").props.onClick(); tree = await settle(d);
  const from = labelled(tree, "Copy setup from");
  assert.deepEqual(nodes(from).filter((n) => n.type === "option").map((n) => n.props.value), ["", "f-1"],
    "a facility never copies from itself");
  type(tree, "Copy setup from", "f-1"); tree = await settle(d);
  await button(tree, "Copy setup").props.onClick(); tree = await settle(d);
  assert.deepEqual(d.calls.map((c) => c[0]), ["update", "admin", "copy"]);
  assert.deepEqual(d.calls[0], ["update", "f-2", { hfr_facility_id: "IN2710005985" }]);
  assert.deepEqual(d.calls[2], ["copy", "f-2", "f-1"]);
  assert.match(content(tree), /Copied 42 departments, 3 rooms, 1 wards, 2 stores and 23 tariff rows/);
});

test("an email-style username is refused before the server, with the reason shown", async () => {
  const d = panel();
  let tree = d.render();
  type(tree, "Facility to set up", "f-2"); tree = await settle(d);
  type(tree, "Admin username", "dev2@example.org"); type(tree, "Admin full name", "Second Admin");
  type(tree, "Temporary password", "Synthetic#Pass1"); tree = await settle(d);
  assert.equal(button(tree, "Create first admin").props.disabled, true);
  assert.match(content(tree), /not an email/);
  type(tree, "Admin username", "dev2.admin"); tree = await settle(d);
  assert.equal(button(tree, "Create first admin").props.disabled, false);
});
