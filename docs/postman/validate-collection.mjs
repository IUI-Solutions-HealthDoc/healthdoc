// Local contract/guard tests only; no network, Vault or Postman workspace access.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const collection = JSON.parse(readFileSync(new URL("./healthdoc-abdm-readiness.postman_collection.json", import.meta.url)));
const requests = collection.item.flatMap(folder => folder.item);
assert.equal(requests.length, 21);
function expect(value, negative = false) {
  const chain = {
    equal(other) { assert.equal(Object.is(value, other), !negative); return chain; },
    match(pattern) { assert.equal(pattern.test(value), !negative); return chain; },
    a(type) { assert.equal(typeof value === type, !negative); return chain; }
  };
  for (const key of ["to", "be", "and"]) Object.defineProperty(chain, key, { get: () => chain });
  Object.defineProperty(chain, "not", { get: () => expect(value, !negative) });
  Object.defineProperty(chain, "empty", { get() { assert.equal(value.length === 0, !negative); return chain; } });
  return chain;
}
const source = (request, event) => request.event.find(e => e.listen === event).script.exec.join("\n");
async function execute(request, event, options = {}) {
  const writes = new Map(), store = new Map(Object.entries(options.collection ?? {}));
  const failures = [], passes = [];
  let skipped = false, vaultReads = 0;
  const responseCode = options.status ?? 200;
  const pm = {
    request: { url: { toString: () => options.url ?? request.request.url } },
    variables: { replaceIn: value => value === "{{$guid}}" ? "00000000-0000-4000-8000-000000000001" : value, set() {} },
    collectionVariables: { get: key => store.get(key), set: (key, value) => store.set(key, value) },
    execution: { skipRequest() { skipped = true; } },
    vault: {
      async get() { vaultReads++; if (options.vaultError) throw Error("synthetic refusal"); return options.vault; },
      async set(key, value) { writes.set(key, value); }
    },
    response: {
      code: responseCode,
      to: { have: { status: expected => assert.equal(responseCode, expected) } },
      json: () => options.body,
      headers: { get: () => options.receipt }
    },
    expect,
    test(name, fn) { try { fn(); passes.push(name); } catch { failures.push(name); } }
  };
  let error;
  try { await new vm.Script("(async () => {\n" + source(request, event) + "\n})()").runInNewContext({ pm, Date, Number, Error }); }
  catch (caught) { error = caught; }
  return { skipped, writes, store, failures, passes, error, vaultReads };
}
for (const r of requests) {
  const url = new URL(r.request.url);
  assert.equal(url.protocol, "https:");
  assert.ok(["localhost", "abdm.healthdoc.world", "dev.abdm.gov.in"].includes(url.hostname));
  assert.equal(r.protocolProfileBehavior.followRedirects, false);
  assert.deepEqual(r.response, []);
  for (const e of ["prerequest", "test"]) new vm.Script("(async () => {\n" + source(r, e) + "\n})()");
  const refused = await execute(r, "prerequest", { url: "https://example.invalid/" });
  assert.equal(refused.skipped, true);
  assert.equal(refused.vaultReads, 0);
  assert.ok(refused.error);
  if (r.request.body) JSON.parse(r.request.body.raw);
}
const session = requests.find(r => r.name.startsWith("01 Session"));
assert.equal((await execute(session, "prerequest")).skipped, true);
assert.equal((await execute(session, "prerequest", { collection: { arm_session_once: "yes" } })).skipped, true);
assert.equal((await execute(session, "prerequest", { collection: { arm_session_once: "yes" }, vaultError: true })).skipped, true);
const approved = await execute(session, "prerequest", { collection: { arm_session_once: "yes" }, vault: "SYNTHETIC-TEST-SECRET" });
assert.equal(approved.skipped, false);
assert.equal(approved.error, undefined);
assert.equal(approved.store.get("arm_session_once"), "no");
const validSession = await execute(session, "test", { body: { accessToken: "SYNTHETIC-TEST-TOKEN", expiresIn: 1200 } });
assert.equal(validSession.writes.get("healthdoc-abdm-access-token"), "SYNTHETIC-TEST-TOKEN");
for (const body of [{ accessToken: "", expiresIn: 1200 }, { accessToken: "SYNTHETIC", expiresIn: 0 }, {}]) {
  const result = await execute(session, "test", { body });
  assert.equal(result.writes.size, 0); assert.ok(result.failures.length);
}
for (const r of requests.filter(r => r.request.auth.type === "bearer")) {
  assert.equal((await execute(r, "prerequest")).skipped, true);
  assert.equal((await execute(r, "prerequest", { vault: "SYNTHETIC" })).skipped, false);
}
const receipt = "00000000-0000-4000-8000-000000000001";
for (const r of requests.filter(r => r.request.url.startsWith("https://abdm.healthdoc.world"))) {
  const status = r.request.method === "GET" ? 405 : 400;
  assert.deepEqual((await execute(r, "test", { status, receipt })).failures, []);
  assert.ok((await execute(r, "test", { status: 200, receipt })).failures.length);
  assert.ok((await execute(r, "test", { status, receipt: undefined })).failures.length);
}
const service = requests.find(r => r.name.startsWith("03 Read"));
const serviceBody = { bridgeId: "SBXID_053401", serviceId: "IN0910034387", isHip: true, isHiu: true, active: true };
assert.deepEqual((await execute(service, "test", { body: serviceBody })).failures, []);
for (const change of [{ serviceId: "WRONG" }, { bridgeId: "WRONG" }, { isHip: false }, { isHiu: false }, { active: false }]) {
  assert.ok((await execute(service, "test", { body: { ...serviceBody, ...change } })).failures.length);
}
const bridge = requests.find(r => r.name.startsWith("02 Read"));
const bridgeBody = { bridge: { id: "SBXID_053401", url: "https://abdm.healthdoc.world", active: true }, services: [{ id: "IN0910034387", active: true }] };
assert.deepEqual((await execute(bridge, "test", { body: bridgeBody })).failures, []);
assert.ok((await execute(bridge, "test", { body: { ...bridgeBody, services: [] } })).failures.length);
assert.ok((await execute(bridge, "test", { body: { ...bridgeBody, bridge: { ...bridgeBody.bridge, url: "https://example.invalid" } } })).failures.length);
console.log("PASS: 21 requests / 42 scripts; destination guards, session arming, missing Vault refusal, token storage validation, expected statuses, receipt checks and registration mismatch mutations.");
console.log("Synthetic local contract tests only: not live Postman, NHA or milestone acceptance.");
