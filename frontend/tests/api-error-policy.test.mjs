import assert from "node:assert/strict";
import test from "node:test";

import { userFacingApiError } from "../src/lib/api-error-policy.mjs";

test("structured validation payloads never become user-facing JSON", () => {
  const payload = {
    detail: [
      { type: "value_error", loc: ["body", "email"], input: "private@example.test" },
    ],
  };
  const message = userFacingApiError(422, payload);

  assert.equal(message, "Please check the highlighted fields and try again.");
  assert.doesNotMatch(message, /private|loc|input|\{|\[/);
});

test("safe domain conflicts remain actionable", () => {
  assert.equal(
    userFacingApiError(409, { detail: { code: "self_approval" } }),
    "You cannot approve or reject your own request.",
  );
  assert.equal(
    userFacingApiError(503, "upstream database host db.internal refused connection"),
    "The service is temporarily unavailable. Try again shortly.",
  );
});

test("a duplicate ABHA bind is not presented as a stale record to reload", () => {
  const message = userFacingApiError(409, {
    code: "duplicate_abha",
    message: "This ABHA number is already linked to another patient",
  });
  assert.match(message, /already linked to another patient/);
  assert.doesNotMatch(message, /Reload|conflicts with the record/);
  assert.match(
    userFacingApiError(400, { code: "enrolment_consent_refused" }),
    /does not consent/,
  );
});

test("an ABDM rejection is not presented as a temporary outage or raw gateway text", () => {
  const message = userFacingApiError(502, {
    code: "abdm_rejected",
    message: "private-identifier private-otp upstream internal response",
  });
  assert.equal(message, "ABDM declined this request. Check the details before retrying; contact support if it continues.");
  assert.doesNotMatch(message, /private|temporarily unavailable|internal/);
  assert.equal(userFacingApiError(503), "The service is temporarily unavailable. Try again shortly.");
});

test("a licence that does not match its record says so, not 'highlighted fields'", () => {
  // Live, 3 Oct 2026: ABDM-1203 "The details provided by you do not match
  // against your documents details" reached the desk as the generic 400 copy.
  const message = userFacingApiError(400, { code: "abha_licence_rejected", message: "server text" });
  assert.match(message, /did not match these details to the driving licence record/);
  assert.match(message, /exactly as printed/);
  assert.doesNotMatch(message, /highlighted fields|server text/);
});

test("a server fault is not presented as a temporary outage", () => {
  for (const status of [500, 501]) {
    const message = userFacingApiError(status, "Traceback: private stack frame");
    assert.equal(message, "Something went wrong on the server. Report it to IT if it happens again.");
    assert.doesNotMatch(message, /temporarily|private|Traceback/);
  }
  for (const status of [502, 503, 504]) {
    assert.equal(userFacingApiError(status), "The service is temporarily unavailable. Try again shortly.");
  }
});

test("staff provisioning failures explain the remedy without hiding role denials", () => {
  for (const payload of [
    { code: "actor_not_provisioned", message: "PRIVATE-SUBJECT" },
    { detail: { code: "actor_not_provisioned", detail: "PRIVATE-SUBJECT" } },
    { code: 403, message: { code: "actor_not_provisioned", detail: "PRIVATE-SUBJECT" } },
  ]) {
    const message = userFacingApiError(403, payload);
    assert.match(message, /Sign-in succeeded.*staff profile.*administrator/);
    assert.doesNotMatch(message, /PRIVATE/);
  }
  assert.match(userFacingApiError(403, { code: "user_deactivated" }), /deactivated.*administrator/);
  assert.equal(userFacingApiError(403, { detail: "Requires doctor role" }), "You do not have permission to perform this action.");
});

test("requester profile errors consistently describe all three registration fields", () => {
  const message = userFacingApiError(422, { code: "invalid_abdm_requester_profile" });
  assert.match(message, /registration number, identifier type and issuing registry URI/);
  assert.match(message, /all three/);
});

test("ABHA enrolment refusals name their cause instead of 'highlighted fields' or an outage", () => {
  // Live, 6 Oct 2026: a missing mobile, a refused mobile and a UIDAI outage
  // all reached the desk as the generic 400/503 copy.
  const cases = [
    [400, "otp_rejected", /did not accept this OTP/],
    [422, "abha_mobile_required", /10-digit mobile number/],
    [400, "abha_mobile_rejected", /did not accept this mobile number/],
    [503, "aadhaar_service_unavailable", /Aadhaar \(UIDAI\) service/],
  ];
  for (const [status, code, expected] of cases) {
    const message = userFacingApiError(status, { code, message: "server text 9876543210" });
    assert.match(message, expected);
    assert.doesNotMatch(message, /highlighted fields|temporarily unavailable|server text|9876543210/);
  }
  // Configuration faults share abdm_unavailable; it keeps the neutral copy.
  assert.equal(
    userFacingApiError(503, { code: "abdm_unavailable" }),
    "The service is temporarily unavailable. Try again shortly.",
  );
});
