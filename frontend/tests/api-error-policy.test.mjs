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

test("an ABDM rejection is not presented as a temporary outage or raw gateway text", () => {
  const message = userFacingApiError(502, {
    code: "abdm_rejected",
    message: "private-identifier private-otp upstream internal response",
  });
  assert.equal(message, "ABDM declined this request. Check the details before retrying; contact support if it continues.");
  assert.doesNotMatch(message, /private|temporarily unavailable|internal/);
  assert.equal(userFacingApiError(503), "The service is temporarily unavailable. Try again shortly.");
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
