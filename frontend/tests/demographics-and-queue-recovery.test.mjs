import assert from "node:assert/strict";
import test from "node:test";

import { compile } from "./helpers/component-harness.mjs";

const { deriveAgeFromDob } = compile(
  new URL("../src/features/receptionist/patientValidation.ts", import.meta.url),
  {},
);

test("deriveAgeFromDob accurately computes newborn age in days", () => {
  const refDate = new Date("2026-09-18T10:00:00Z");
  const dob = "2026-09-10"; // 8 days old
  const res = deriveAgeFromDob(dob, refDate);
  assert.ok(res);
  assert.equal(res.years, 0);
  assert.equal(res.months, 0);
  assert.equal(res.days, 8);
  assert.equal(res.displayText, "8 days (Newborn)");
});

test("deriveAgeFromDob accurately computes infant age in months and days", () => {
  const refDate = new Date("2026-09-18T10:00:00Z");
  const dob = "2026-05-10"; // ~4 months
  const res = deriveAgeFromDob(dob, refDate);
  assert.ok(res);
  assert.equal(res.years, 0);
  assert.equal(res.months, 4);
  assert.equal(res.days, 8);
  assert.equal(res.displayText, "4 months, 8 days (Infant)");
});

test("deriveAgeFromDob accurately computes toddler age in years and months", () => {
  const refDate = new Date("2026-09-18T10:00:00Z");
  const dob = "2024-03-15"; // 2 years, 6 months
  const res = deriveAgeFromDob(dob, refDate);
  assert.ok(res);
  assert.equal(res.years, 2);
  assert.equal(res.months, 6);
  assert.equal(res.displayText, "2 years, 6 months");
});

test("deriveAgeFromDob accurately computes adult age in years", () => {
  const refDate = new Date("2026-09-18T10:00:00Z");
  const dob = "1990-01-01"; // 36 years
  const res = deriveAgeFromDob(dob, refDate);
  assert.ok(res);
  assert.equal(res.years, 36);
  assert.equal(res.displayText, "36 years");
});

test("deriveAgeFromDob rejects future dates or invalid strings", () => {
  const refDate = new Date("2026-09-18T10:00:00Z");
  assert.equal(deriveAgeFromDob("2099-01-01", refDate), null);
  assert.equal(deriveAgeFromDob("", refDate), null);
  assert.equal(deriveAgeFromDob("not-a-date", refDate), null);
});
