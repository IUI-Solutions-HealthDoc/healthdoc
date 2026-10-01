import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";

const collection = JSON.parse(readFileSync(new URL("./healthdoc-webhook-inspector.postman_collection.json", import.meta.url)));
assert.equal(collection.item.length, 4);
const source = collection.event.find(e => e.listen === "prerequest").script.exec.join("\n");
for (const event of collection.event) new vm.Script(event.script.exec.join("\n"));
function run(url, method = "GET") {
  let skipped = false, error;
  const pm = {request: {method, url: {toString: () => url}}, variables: {replaceIn: text => text}, execution: {skipRequest: () => {skipped = true;}}};
  try { new vm.Script(source).runInNewContext({pm, Error}); } catch(e) { error = e; }
  return {skipped, error};
}
for (const item of collection.item) {
  assert.equal(item.request.method, "GET");
  assert.equal(item.protocolProfileBehavior.followRedirects, false);
  assert.deepEqual(item.response, []);
  const url = item.request.url.replace(/\{\{[^}]+\}\}/g, "00000000-0000-4000-8000-000000000001");
  assert.deepEqual(run(url), {skipped: false, error: undefined});
  assert.ok(run(url, "POST").skipped);
}
for (const url of ["https://example.invalid/api/receipts", "http://127.0.0.1:8766@evil.invalid/api/receipts", "http://127.0.0.1:8766/api/receipts/extra", "http://127.0.0.1:8766/api/receipt?id=REPLACE_WITH_RECEIPT_UUID"]) {
  const result = run(url); assert.ok(result.skipped && result.error);
}
console.log("PASS: 4 read-only local inspector requests; destination/method/placeholder guards and empty saved responses.");
