import assert from "node:assert/strict";
import test from "node:test";
import { compile, componentHarness, flush, nodes, content } from "./helpers/component-harness.mjs";
const source = (path) => new URL(`../src/features/doctor/${path}`, import.meta.url);
const file = () => new File(["%PDF synthetic"], "outside.pdf", { type: "application/pdf" });
const metadata = { id: "F", patient_id: "P", erased_at: null, original_name: "outside.pdf" };
const attachmentClient = (api) => compile(source("api/externalAttachments.ts"), { "@/lib/api": { api } });

test("shared client sends bearer-authenticated multipart without a JSON Content-Type; JSON calls keep existing headers", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (...args) => {
    calls.push(args); return Response.json({ success: true, data: metadata, error: null, meta: {} });
  });
  const client = compile(new URL("../src/lib/api.ts", import.meta.url), {
    "./api-error-policy.mjs": {}, "./session-policy.mjs": {}, "./auth": {},
  });
  client.setAccessToken("synthetic-token");
  const body = new FormData(); body.append("upload", file());
  await client.api("/files/upload", { method: "POST", body, idempotencyKey: null });
  const headers = new Headers(calls[0][1].headers);
  assert.equal(headers.has("Content-Type"), false);
  assert.equal(headers.get("Authorization"), "Bearer synthetic-token");
  assert.equal(calls[0][1].body, body);
  await client.api("/orders/A/external-results", { method: "POST", body: "{}", idempotencyKey: "key" });
  assert.equal(new Headers(calls[1][1].headers).get("Content-Type"), "application/json");
  assert.equal(new Headers(calls[1][1].headers).get("Idempotency-Key"), "key");
});

test("upload validates size/format, binds patient and sensitivity, and refuses mismatched/erased receipts", async () => {
  const calls = []; let response = metadata;
  const client = attachmentClient(async (...args) => { calls.push(args); return response; });
  assert.equal(client.validateResultFile(file()), null);
  for (const bad of [{ size: 0, name: "test.pdf" }, { size: 26 * 1024 * 1024, name: "test.pdf" }, { size: 4, name: "test.html" }]) {
    await assert.rejects(client.uploadResultFile(bad, "P"));
  }
  assert.equal(calls.length, 0);
  assert.deepEqual(await client.uploadResultFile(file(), "P"), metadata);
  const [path, options] = calls[0]; assert.equal(path, "/files/upload");
  assert.equal(options.body.get("patient_id"), "P");
  assert.equal(options.body.get("owner_module"), "orders");
  assert.equal(options.body.get("sensitivity"), "sensitive");
  assert.equal(options.body.get("upload").name, "outside.pdf");
  assert.equal(options.idempotencyKey, null, "no invented upload replay protocol");
  for (const bad of [{ ...metadata, patient_id: "other" }, { ...metadata, erased_at: "2026-01-01" }]) {
    response = bad; await assert.rejects(client.uploadResultFile(file(), "P"), /match.*patient/);
  }
});

test("download checks file identity/patient before signing and rejects unsafe addresses", async () => {
  const calls = []; let record = metadata, link = { url: "https://files.example.test/report?signed=synthetic", expires_in_seconds: 300 };
  const client = attachmentClient(async (path) => { calls.push(path); return path.endsWith("download-url") ? link : record; });
  assert.equal((await client.prepareResultDownload("F", "P")).url, link.url);
  assert.deepEqual(calls, ["/files/F", "/files/F/download-url"]);
  for (const bad of [{ ...metadata, patient_id: "other" }, { ...metadata, id: "wrong" }, { ...metadata, erased_at: "2026-01-01" }]) {
    calls.length = 0; record = bad; await assert.rejects(client.prepareResultDownload("F", "P"));
    assert.equal(calls.length, 1, "must not request a download URL for wrong/erased metadata");
  }
  record = metadata;
  for (const url of ["javascript:alert(1)", "data:text/plain,report", "http://files.example.test/report", "https://name:password@files.example.test/report"]) {
    link = { url, expires_in_seconds: 300 }; await assert.rejects(client.prepareResultDownload("F", "P"), /safely configured/);
  }
  link = { url: "http://localhost:9000/report", expires_in_seconds: 300 };
  assert.equal((await client.prepareResultDownload("F", "P")).url, link.url);
  link.expires_in_seconds = 0; await assert.rejects(client.prepareResultDownload("F", "P"));
});

class ApiError extends Error { constructor(code) { super("rejected"); this.code = code; } }
function harness(component = "ExternalResultUpload") {
  const calls = [], changes = [];
  const client = attachmentClient(() => {});
  const request = (name) => (...args) => new Promise((resolve, reject) => calls.push({ name, args, resolve, reject }));
  const ui = componentHarness((deps) => {
    for (const name of ["Alert", "Stack"]) deps[`@mui/material/${name}`] = { default: name };
    deps["@/components/ui/Button"] = { Button: "button" };
    deps["@/lib/api"] = { ApiError, getUserFacingError: (_e, fallback) => fallback };
    deps["../api/externalAttachments"] = { validateResultFile: client.validateResultFile,
      uploadResultFile: request("upload"), prepareResultDownload: request("download") };
    const Panel = compile(source("components/ExternalResultAttachment.tsx"), deps)[component];
    // Same keyed boundary as the owning result panel: switch removes old hooks.
    return (props) => deps["react/jsx-runtime"].jsx(Panel, props, `${props.patientId}:${props.fileId ?? "upload"}`);
  });
  const props = { patientId: "P", disabled: false, fileId: "F", onChange: (value) => changes.push(value) };
  return { ...ui, calls, changes, props };
}
const button = (tree, label) => nodes(tree).find((node) => node.type === "button" && content(node) === label);
const choose = (ui) => nodes(ui.render(ui.props)).find((n) => n.type === "input").props.onChange({ target: { files: [file()] } });

test("uncertain uploads block duplicates and retain warning; switching patient ignores late upload receipt", async () => {
  const ui = harness(); ui.render(ui.props); ui.effects(); choose(ui);
  assert.deepEqual(ui.changes.at(-1), { fileId: null, blocked: true });
  button(ui.render(ui.props), "Upload attachment").props.onClick();
  button(ui.render(ui.props), "Uploading attachment…").props.onClick(); assert.equal(ui.calls.length, 1);
  ui.calls[0].reject(new Error("transport lost")); await flush();
  let tree = ui.render(ui.props); assert.match(content(tree), /outcome is unknown/);
  assert.equal(button(tree, "Upload attachment").props.disabled, true);
  button(tree, "Upload attachment").props.onClick(); assert.equal(ui.calls.length, 1);
  assert.equal(button(tree, "Remove attachment selection").props.disabled, true);
  const other = { ...ui.props, patientId: "Q" }; ui.render(other); ui.effects();
  assert.doesNotMatch(content(ui.render(other)), /outcome is unknown/);
  nodes(ui.render(other)).find((n) => n.type === "input").props.onChange({ target: { files: [file()] } });
  button(ui.render(other), "Upload attachment").props.onClick(); const late = ui.calls.at(-1);
  ui.render(ui.props); ui.effects(); const before = ui.changes.length;
  late.resolve({ ...metadata, patient_id: "Q" }); await flush();
  assert.equal(ui.changes.length, before); assert.doesNotMatch(content(ui.render(ui.props)), /Uploaded:/);
});

test("confirmed upload can be linked or removed, and explicit rejection permits correction", async () => {
  const ui = harness(); ui.render(ui.props); ui.effects(); choose(ui);
  button(ui.render(ui.props), "Upload attachment").props.onClick(); ui.calls[0].reject(new ApiError(422)); await flush();
  assert.equal(button(ui.render(ui.props), "Upload attachment").props.disabled, false);
  button(ui.render(ui.props), "Upload attachment").props.onClick(); ui.calls.at(-1).resolve(metadata); await flush();
  assert.deepEqual(ui.changes.at(-1), { fileId: "F", blocked: false });
  assert.match(content(ui.render(ui.props)), /does not erase/);
  button(ui.render(ui.props), "Remove attachment selection").props.onClick();
  assert.deepEqual(ui.changes.at(-1), { fileId: null, blocked: false });
  assert.equal(ui.calls.length, 2, "removing selection sends no erase request");
});

test("download is explicit, stale patient response ignored, expired link cannot navigate", async () => {
  const ui = harness("ExternalResultDownload"); ui.render(ui.props); ui.effects(); assert.equal(ui.calls.length, 0);
  button(ui.render(ui.props), "Prepare attachment download").props.onClick();
  const first = ui.calls[0], other = { ...ui.props, patientId: "Q", fileId: "G" };
  ui.render(other); ui.effects(); first.resolve({ url: "https://files.example.test/private", name: "Patient P", expiresAt: Date.now() + 10000 }); await flush();
  assert.equal(nodes(ui.render(other)).some((n) => n.type === "a"), false);
  button(ui.render(other), "Prepare attachment download").props.onClick();
  ui.calls.at(-1).resolve({ url: "https://files.example.test/report", name: "Patient Q", expiresAt: Date.now() - 1 }); await flush();
  const link = nodes(ui.render(other)).find((n) => n.type === "a");
  assert.equal(link.props.rel, "noopener noreferrer"); assert.equal(link.props.referrerPolicy, "no-referrer");
  let prevented = false; link.props.onClick({ preventDefault() { prevented = true; } });
  assert.equal(prevented, true); assert.match(content(ui.render(other)), /expired/);
});
