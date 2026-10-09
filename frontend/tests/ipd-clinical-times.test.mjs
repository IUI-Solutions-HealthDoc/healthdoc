import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

// A datetime-local value is wall-clock time with no zone. Sent bare, the
// server read it as UTC and stored an IST admission 5½ hours in the future.
function loadIpdApi() {
  const calls = [];
  const source = readFileSync(new URL("../src/features/ipd/api/ipd.ts", import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const exports = {};
  const dependencies = {
    "@/lib/api": { api: async (path, options) => { calls.push({ path, ...options }); }, newIdempotencyKey: () => "synthetic-key" },
  };
  new Function("require", "exports", compiled)((name) => dependencies[name] ?? {}, exports);
  return { ...exports, calls };
}

test("admission and discharge times leave the browser as exact UTC instants", async () => {
  const api = loadIpdApi();
  const local = "2026-10-09T14:33";
  const expected = new Date(local).toISOString();
  await api.admitPatient({ visit_id: "v", ward_id: "w", bed_id: "b", admitted_at: local, reason: "" });
  await api.dischargePatient({ admission_id: "a", discharge_type: "discharged", discharged_at: local, follow_up_date: "" });
  assert.equal(JSON.parse(api.calls[0].body).admitted_at, expected);
  assert.equal(JSON.parse(api.calls[1].body).discharged_at, expected);
  assert.match(expected, /Z$/);
});

test("an empty or invalid time is omitted rather than sent as a guess", () => {
  const api = loadIpdApi();
  assert.equal(api.localDateTimeToIso(""), undefined);
  assert.equal(api.localDateTimeToIso(undefined), undefined);
  assert.equal(api.localDateTimeToIso("not a time"), undefined);
});
