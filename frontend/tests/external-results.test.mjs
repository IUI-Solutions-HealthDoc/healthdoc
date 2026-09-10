import assert from "node:assert/strict";
import test from "node:test";
import { z } from "zod";
import { compile, componentHarness, flush, nodes, content } from "./helpers/component-harness.mjs";
const source = (path) => new URL(`../src/features/doctor/${path}`, import.meta.url);
const schema = compile(source("lib/external-result-form.ts"), { zod: { z } }).externalResultSchema;

test("outside-result form normalizes blanks and rejects missing summaries, impossible/future dates and oversized text", () => {
  const form = schema("2026-09-10"), valid = { summary: " Outside report ", provider_name: " ", observed_on: "" };
  assert.deepEqual(form.parse(valid), { summary: "Outside report", provider_name: null, observed_on: null });
  for (const change of [{ summary: " " }, { summary: "x".repeat(10001) }, { provider_name: "x".repeat(501) },
    ...["2026-02-30", "2026-09-11", "2026-09-10T00:00:00Z", "not-a-date"].map((observed_on) => ({ observed_on }))]) {
    assert.equal(form.safeParse({ ...valid, ...change }).success, false, JSON.stringify(change));
  }
  assert.equal(form.parse({ ...valid, observed_on: "2026-09-10" }).observed_on, "2026-09-10");
});

test("result adapters preserve bodies/keys, reject wrong-order history and propagate failures", async () => {
  const calls = []; let response = { items: [] };
  const client = compile(source("api/externalResults.ts"), { "@/lib/api": { api: async (...args) => {
    calls.push(args); if (response instanceof Error) throw response; return response;
  } } });
  assert.deepEqual(await client.listExternalResults("a/b"), []);
  assert.equal(calls[0][0], "/orders/a%2Fb/external-results");
  response = { items: [{ order_id: "wrong" }] };
  await assert.rejects(client.listExternalResults("A"), /Invalid/);
  response = new Error("failure"); await assert.rejects(client.listExternalResults("A"), /failure/);
  response = { id: "R", order_id: "A" };
  const body = { summary: "Report", provider_name: null, observed_on: null };
  await client.recordExternalResult("A", body, "stable");
  assert.equal(calls.at(-1)[1].idempotencyKey, "stable");
  assert.deepEqual(JSON.parse(calls.at(-1)[1].body), body);
});

for (const type of ["lab", "radiology"]) test(`${type} external referral never calls a disabled local department`, async () => {
  const calls = [];
  const client = compile(source("api/orders.ts"), { "@/lib/api": { api: async (...args) => {
    calls.push(args); return { id: "A", fulfilment_mode: "external_referral", order_type: type };
  } } });
  const placed = await client.placeOrder({ order_type: type, priority: "routine", test_name: "Outside test", scan_type: "Outside scan" },
    { encounter_id: "E", patient_id: "P" }, "key");
  assert.equal(calls.length, 1); assert.equal(calls[0][0], "/orders");
  assert.equal(placed.fulfilment_mode, "external_referral"); assert.equal(placed.detail_status, "header_only");
});

test("legacy order replay must resolve its mode; unknown never falls through to local fulfilment", async () => {
  const calls = []; let mode = null;
  const client = compile(source("api/orders.ts"), { "@/lib/api": { api: async (...args) => {
    calls.push(args); return { id: "A", fulfilment_mode: args[0] === "/orders" ? null : mode };
  } } });
  const draft = { order_type: "lab", priority: "routine", test_name: "Test" }, ctx = { encounter_id: "E", patient_id: "P" };
  assert.equal((await client.placeOrder(draft, ctx, "key")).detail_status, "failed");
  assert.deepEqual(calls.map(([path]) => path), ["/orders", "/orders/A"]);
  calls.length = 0; mode = "external_referral";
  assert.equal((await client.placeOrder(draft, ctx, "key")).fulfilment_mode, mode);
  assert.equal(calls.length, 2);
});

test("internal lab orders retain the clinical detail call and stable detail action key", async () => {
  const calls = [];
  const client = compile(source("api/orders.ts"), { "@/lib/api": { api: async (...args) => {
    calls.push(args); return args[0] === "/orders" ? { id: "A", fulfilment_mode: "internal" } : { accession_number: "LAB-1" };
  } } });
  const placed = await client.placeOrder({ order_type: "lab", priority: "routine", test_name: "CBC", sample_type: "blood" },
    { encounter_id: "E", patient_id: "P" }, "key");
  assert.equal(calls[1][0], "/pathology/order-items?order_id=A");
  assert.equal(calls[1][1].idempotencyKey, "key:detail"); assert.equal(placed.accession_number, "LAB-1");
});

function harness() {
  const calls = []; let keys = 0, saved = 0;
  const request = (name) => (...args) => new Promise((resolve, reject) => calls.push({ name, args, resolve, reject }));
  const ui = componentHarness((deps) => {
    for (const name of ["Alert", "Box", "Stack", "TextField", "Typography"]) deps[`@mui/material/${name}`] = { default: name };
    deps["@/components/ui/Button"] = { Button: "button" };
    deps["@/lib/api"] = { ApiError: class extends Error {}, formatDateTime: (v) => v,
      getUserFacingError: (_e, fallback) => fallback, newIdempotencyKey: () => `key-${++keys}` };
    deps["../api/externalResults"] = { listExternalResults: request("list"), recordExternalResult: request("save") };
    deps["../lib/external-result-form"] = { externalResultSchema: schema };
    deps["./ExternalResultAttachment"] = { ExternalResultUpload: "Upload", ExternalResultDownload: "Download" };
    return compile(source("components/ExternalResultPanel.tsx"), deps).ExternalResultPanel;
  });
  const props = (id, extra = {}) => ({ patientId: `P-${id}`, patientLabel: `Patient ${id}`, order: {
    id, order_number: `ORD-${id}`, status: "placed", fulfilment_mode: "external_referral", ...extra,
  }, onSaved: () => saved++ });
  return { ...ui, calls, props, saved: () => saved };
}
const button = (tree, label) => nodes(tree).find((node) => node.type === "button" && content(node) === label);
function fill(ui, props, summary = "Outside summary") {
  let tree = ui.render(props);
  nodes(tree).find((node) => node.props?.label === "Outside result summary").props.onChange({ target: { value: summary } });
  tree = ui.render(props);
  nodes(tree).find((node) => node.type === "input" && node.props.type === "checkbox").props.onChange({ target: { checked: true } });
}
function submit(ui, props) { nodes(ui.render(props)).find((node) => node.props?.component === "form").props.onSubmit({ preventDefault() {} }); }

test("form errors stop writes, failed history is not an empty list, and unknown/cancelled orders cannot be submitted", async () => {
  const ui = harness(), props = ui.props("A");
  ui.render(props); ui.effects(); ui.calls[0].resolve([]); await flush();
  submit(ui, props);
  assert.equal(ui.calls.filter((c) => c.name === "save").length, 0);
  assert.ok(nodes(ui.render(props)).some((node) => node.props?.helperText === "Enter the outside result summary."));
  assert.match(content(ui.render(props)), /Confirm the patient/);
  button(ui.render(props), "Refresh result history").props.onClick();
  ui.calls[1].reject(new Error("failed")); await flush();
  assert.match(content(ui.render(props)), /history could not be loaded/);
  assert.doesNotMatch(content(ui.render(props)), /No outside results recorded/);
  assert.equal(nodes(ui.render(ui.props("B", { status: "cancelled" }))).some((node) => node.props?.component === "form"), false);
  const before = ui.calls.length;
  assert.match(content(ui.render(ui.props("C", { fulfilment_mode: null }))), /not confirmed/); ui.effects();
  assert.equal(ui.calls.length, before);
});

test("ambiguous write retries identical payload/key; confirmed save survives failed read-back and prevents double submit", async () => {
  const ui = harness(), props = ui.props("A");
  ui.render(props); ui.effects(); ui.calls[0].resolve([]); await flush();
  fill(ui, props); submit(ui, props); submit(ui, props);
  const first = ui.calls.find((c) => c.name === "save"); assert.equal(ui.calls.filter((c) => c.name === "save").length, 1);
  first.reject(new Error("transport lost")); await flush();
  assert.equal(nodes(ui.render(props)).find((n) => n.props?.label === "Outside result summary").props.disabled, true);
  submit(ui, props); const retry = ui.calls.at(-1); assert.deepEqual(retry.args, first.args);
  retry.resolve({ id: "R", order_id: "A" }); await flush();
  assert.equal(ui.saved(), 1);
  ui.calls.at(-1).reject(new Error("readback failed")); await flush();
  const tree = ui.render(props);
  assert.match(content(tree), /Result recorded for\s+ORD-A/); assert.match(content(tree), /history could not be loaded/);
  assert.equal(nodes(tree).some((node) => node.props?.component === "form"), false);
  button(tree, "Record another result / correction").props.onClick();
  button(ui.render(props), "Refresh result history").props.onClick(); ui.calls.at(-1).resolve([]); await flush();
  fill(ui, props, "Correction"); submit(ui, props);
  assert.notEqual(ui.calls.at(-1).args[2], first.args[2]);
});

test("patient/order switching clears drafts before paint and ignores old history and write completions", async () => {
  const ui = harness(), a = ui.props("A"), b = ui.props("B"), c = ui.props("C");
  ui.render(a); ui.effects(); ui.calls[0].resolve([]); await flush();
  fill(ui, a, "Private A"); submit(ui, a); const save = ui.calls.at(-1);
  let tree = ui.render(b); ui.effects();
  assert.doesNotMatch(content(tree), /Private A|ORD-A/);
  assert.equal(nodes(tree).find((n) => n.props?.label === "Outside result summary").props.value, "");
  const readB = ui.calls.at(-1);
  ui.render(c); ui.effects(); ui.calls.at(-1).resolve([]); await flush();
  readB.resolve([{ id: "B", order_id: "B", summary: "Private B" }]);
  save.resolve({ id: "A", order_id: "A" }); await flush();
  tree = ui.render(c); assert.doesNotMatch(content(tree), /Private B|Result recorded for\s+ORD-A/); assert.equal(ui.saved(), 0);
});

test("pending attachment blocks result submission; confirmed file ID is frozen into exact retry and cleared on correction", async () => {
  const ui = harness(), props = ui.props("A");
  ui.render(props); ui.effects(); ui.calls[0].resolve([]); await flush(); fill(ui, props);
  const upload = () => nodes(ui.render(props)).find((node) => node.type === "Upload");
  upload().props.onChange({ fileId: null, blocked: true }); submit(ui, props);
  assert.equal(ui.calls.filter((call) => call.name === "save").length, 0);
  upload().props.onChange({ fileId: "patient-A-file", blocked: false }); submit(ui, props);
  const save = ui.calls.at(-1);
  assert.equal(save.args[1].result_file_id, "patient-A-file");
  save.reject(new Error("unknown")); await flush();
  assert.equal(upload().props.disabled, true);
  submit(ui, props); assert.deepEqual(ui.calls.at(-1).args, save.args);
  ui.calls.at(-1).resolve({ id: "R", order_id: "A" }); await flush();
  ui.calls.at(-1).resolve([]); await flush();
  button(ui.render(props), "Record another result / correction").props.onClick();
  fill(ui, props, "Correction"); submit(ui, props);
  assert.equal(ui.calls.at(-1).args[1].result_file_id, null);
});
