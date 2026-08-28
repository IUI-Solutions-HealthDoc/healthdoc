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
