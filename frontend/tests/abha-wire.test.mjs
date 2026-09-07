import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

function loadApi() {
  const calls = [];
  function compile(file, dependencies) {
    const source = readFileSync(new URL(file, import.meta.url), "utf8");
    const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
    const exports = {};
    new Function("require", "exports", compiled)((name) => {
      assert.ok(name in dependencies, `Unexpected dependency ${name}`);
      return dependencies[name];
    }, exports);
    return exports;
  }
  const validation = compile("../src/features/receptionist/patientValidation.ts", {});
  const api = compile("../src/features/receptionist/api.ts", {
    "@/lib/api": { api: async (path, options) => { calls.push({ path, ...options }); } },
    "./patientValidation": validation,
  });
  return { ...api, calls };
}

test("ABHA enrolment sends ten national mobile digits, not the patient's E.164 storage format", async () => {
  const api = loadApi();
  for (const mobile of ["+919876543210", "9876543210", "09876543210", "+91 98765 43210"]) {
    await api.verifyAbhaEnrolmentOtp("synthetic-session", "123456", mobile, "synthetic-key");
    const call = api.calls.at(-1);
    assert.equal(call.path, "/abdm/abha/enrol/aadhaar/verify-otp");
    assert.deepEqual(JSON.parse(call.body), { session_id: "synthetic-session", otp: "123456", mobile: "9876543210" });
    assert.equal(call.idempotencyKey, "synthetic-key");
  }
});

test("ABHA enrolment permits no optional mobile but refuses invalid nonempty input before transport", async () => {
  const api = loadApi();
  await api.verifyAbhaEnrolmentOtp("synthetic-session", "123456", null, "synthetic-key");
  assert.equal(JSON.parse(api.calls[0].body).mobile, null);
  for (const mobile of ["123", "+449876543210", "invalid"]) {
    await assert.rejects(async () => api.verifyAbhaEnrolmentOtp("synthetic-session", "123456", mobile, "synthetic-key"), /valid.*mobile/i);
  }
  assert.equal(api.calls.length, 1);
});
