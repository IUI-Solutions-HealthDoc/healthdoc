import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

// 29 Sep 2026, live M2 run: a teleconsult opened by visit_id could not save its
// encounter (POST /encounters 422 provider_not_in_facility). The page sent
// useAuth().user.id — the Keycloak subject — as provider_user_id, which is not a
// HealthDoc staff id. The token path fell back to the same value.
const page = readFileSync(new URL("../src/app/doctor/consultation/page.tsx", import.meta.url), "utf8");

test("consultation provider id comes from the staff record, never the auth subject", () => {
  assert.match(page, /getMe\(\)/, "the staff id must come from GET /users/me");
  const providerLines = page.split("\n").filter((line) => line.includes("provider_user_id"));
  assert.ok(providerLines.length >= 2, "both the token and visit_id paths set provider_user_id");
  for (const line of providerLines) {
    assert.doesNotMatch(line, /\buser\??\.id\b/, `auth subject used as provider: ${line.trim()}`);
  }
});
