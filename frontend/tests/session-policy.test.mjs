import assert from "node:assert/strict";
import test from "node:test";

import { idleTimeoutMs, sessionExpiredPath } from "../src/lib/session-policy.mjs";

test("idle timeout defaults safely and accepts a bounded deployment override", () => {
  assert.equal(idleTimeoutMs(undefined), 15 * 60_000);
  assert.equal(idleTimeoutMs("5"), 5 * 60_000);
  assert.equal(idleTimeoutMs("0"), 15 * 60_000);
  assert.equal(idleTimeoutMs("not-a-number"), 15 * 60_000);
  assert.equal(idleTimeoutMs(10_000), 12 * 60 * 60_000);
});

test("expired login redirect preserves only an internal path", () => {
  assert.equal(
    sessionExpiredPath("/doctor/consultation", "?visit=123"),
    "/login?reason=session-expired&redirect=%2Fdoctor%2Fconsultation%3Fvisit%3D123",
  );
  assert.equal(sessionExpiredPath("/login"), "/login?reason=session-expired");
  assert.equal(sessionExpiredPath("/login", "?reason=session-expired"), "/login?reason=session-expired");
  assert.equal(new URLSearchParams(sessionExpiredPath("/doctor", "?visit=1", "#notes").split("?")[1]).get("redirect"), "/doctor?visit=1#notes");
});
