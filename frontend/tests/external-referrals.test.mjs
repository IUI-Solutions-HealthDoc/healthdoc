import assert from "node:assert/strict";
import test from "node:test";
import { compile, componentHarness, flush, nodes, content } from "./helpers/component-harness.mjs";
const source = (path) => new URL(`../src/features/doctor/${path}`, import.meta.url);
const referral = (id) => ({ id, patient_id: `P-${id}`, patient_name: `Patient ${id}`, patient_identifier: `UHID-${id}`,
  visit_number: `V-${id}`, order_number: `ORD-${id}`, fulfilment_mode: "external_referral", order_type: "lab", result_count: 0 });
const page = (items, offset = 0, total = items.length) => ({ items, total, offset, limit: 25 });
const button = (tree, label) => nodes(tree).find((node) => node.type === "button" && content(node) === label);

test("inbox adapter validates page, carries status/pagination and never turns a failure into empty success", async () => {
  const calls = []; let result = page([referral("A")]);
  const client = compile(source("api/externalReferrals.ts"), { "@/lib/api": { api: async (...args) => {
    calls.push(args); if (result instanceof Error) throw result; return result;
  } } });
  assert.deepEqual(await client.listExternalReferrals("pending", 0), result);
  assert.equal(calls[0][0], "/orders/external-referrals?state=pending&offset=0&limit=25");
  for (const bad of [{ ...result, offset: 25 }, { ...result, total: -1 }, { ...result, items: null },
    page([{ ...referral("A"), fulfilment_mode: "internal" }]), page([{ ...referral("A"), patient_id: null }])]) {
    result = bad; await assert.rejects(client.listExternalReferrals("pending", 0), /Invalid/);
  }
  result = new Error("failure"); await assert.rejects(client.listExternalReferrals("pending", 0), /failure/);
});

function harness() {
  const calls = [];
  const ui = componentHarness((deps) => {
    for (const name of ["Alert", "Box", "Stack", "Typography"]) deps[`@mui/material/${name}`] = { default: name };
    deps["@/components/ui/Button"] = { Button: "button" };
    deps["@/lib/api"] = { formatDateTime: (v) => v, getUserFacingError: (_e, fallback) => fallback };
    deps["../api/externalReferrals"] = { listExternalReferrals: (...args) => new Promise((resolve, reject) => calls.push({ args, resolve, reject })) };
    deps["./ExternalResultPanel"] = { ExternalResultPanel: "ResultPanel" };
    return compile(source("components/ExternalReferralInbox.tsx"), deps).ExternalReferralInbox;
  });
  const panel = () => nodes(ui.render({})).find((node) => node.type === "ResultPanel");
  const state = (value) => nodes(ui.render({})).find((node) => node.type === "select").props.onChange({ target: { value } });
  return { ...ui, calls, panel, state };
}

test("inbox works without a queue, paginates, refreshes after receipt and retains selected completed order", async () => {
  const ui = harness(); ui.render({}); ui.effects();
  assert.deepEqual(ui.calls[0].args, ["pending", 0, 25]);
  ui.calls[0].resolve(page([referral("A")], 0, 26)); await flush();
  button(ui.render({}), "Outside results").props.onClick();
  assert.equal(ui.panel().props.patientId, "P-A");
  ui.panel().props.onSaved(); ui.calls.at(-1).resolve(page([], 0, 25)); await flush();
  assert.equal(ui.panel().props.order.id, "A", "receipt owner stays mounted even when removed from pending list");
  button(ui.render({}), "Refresh referrals").props.onClick(); ui.calls.at(-1).resolve(page([referral("B")], 0, 26)); await flush();
  button(ui.render({}), "Next referrals").props.onClick();
  assert.equal(ui.panel(), undefined, "page switch clears the selected patient before fetch"); ui.effects();
  assert.deepEqual(ui.calls.at(-1).args, ["pending", 25, 25]);
  ui.calls.at(-1).resolve(page([referral("C")], 25, 26)); await flush();
  assert.equal(button(ui.render({}), "Next referrals").props.disabled, true);
  ui.state("completed"); ui.render({}); ui.effects();
  assert.deepEqual(ui.calls.at(-1).args, ["completed", 0, 25]);
});

test("filter changes discard old patient details and late responses; failures are not empty success", async () => {
  const ui = harness(); ui.render({}); ui.effects(); const pending = ui.calls[0];
  ui.state("all"); ui.render({}); ui.effects(); const all = ui.calls.at(-1);
  all.resolve(page([referral("B")])); pending.resolve(page([referral("A")])); await flush();
  assert.doesNotMatch(content(ui.render({})), /Patient A/);
  button(ui.render({}), "Outside results").props.onClick(); assert.equal(ui.panel().props.patientId, "P-B");
  ui.state("cancelled"); assert.equal(ui.panel(), undefined); ui.effects();
  ui.calls.at(-1).reject(new Error("failure")); await flush();
  assert.match(content(ui.render({})), /could not be loaded/);
  assert.doesNotMatch(content(ui.render({})), /No referrals on this page/);
});

test("Results review mounts only the chosen source and exposes labelled tabs", () => {
  const ui = componentHarness((deps) => {
    for (const name of ["Alert", "Box", "Tabs", "Tab", "Typography"]) deps[`@mui/material/${name}`] = { default: name };
    deps["@/styles/theme"] = { meridian: {} }; deps["../panelSx"] = {};
    deps["../hooks/useResults"] = { useResults: () => ({ labVersions: [], radVersions: [] }) };
    deps["./ResultDetailPanel"] = { ResultDetailPanel: "LocalDetail" };
    deps["./ResultsWorklistPanel"] = { ResultsWorklistPanel: "LocalList" };
    deps["./ExternalReferralInbox"] = { ExternalReferralInbox: "Inbox" };
    return compile(source("components/ResultsWorkspace.tsx"), deps).ResultsWorkspace;
  });
  let tree = ui.render({}); assert.ok(nodes(tree).some((n) => n.type === "LocalList"));
  assert.equal(nodes(tree).some((n) => n.type === "Inbox"), false);
  nodes(tree).find((n) => n.type === "Tabs").props.onChange(null, "external"); tree = ui.render({});
  assert.ok(nodes(tree).some((n) => n.type === "Inbox")); assert.equal(nodes(tree).some((n) => n.type === "LocalList"), false);
  assert.equal(nodes(tree).find((n) => n.props.role === "tabpanel").props["aria-labelledby"], "external-results-tab");
});
