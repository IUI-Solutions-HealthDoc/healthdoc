import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { compile } from "./helpers/component-harness.mjs";

const validation = compile(
  new URL("../src/features/receptionist/patientValidation.ts", import.meta.url),
  {},
);
const source = (file) =>
  readFileSync(new URL(`../src/features/receptionist/${file}`, import.meta.url), "utf8");

test("localToday is the machine's calendar day, not the UTC one", () => {
  // 01:30 local on 1 October; in IST that instant is still 30 September in UTC.
  const lateNight = new Date(2026, 9, 1, 1, 30);
  assert.equal(validation.localToday(lateNight), "2026-10-01");
  assert.equal(validation.localToday(new Date(2026, 0, 5, 12)), "2026-01-05");
});

test("PIN codes are six digits that do not start with 0", () => {
  for (const ok of ["110070", "560100", " 400001 "]) assert.equal(validation.isValidPincodeInput(ok), true, ok);
  for (const bad of ["011007", "11007", "1100701", "11OO70", ""]) {
    assert.equal(validation.isValidPincodeInput(bad), false, bad);
  }
});

test("state must be one of the listed codes", () => {
  const codes = validation.INDIAN_STATES.map((state) => state.code);
  assert.equal(new Set(codes).size, codes.length, "state codes are unique");
  for (const code of ["DL", "MH", "KA", "TG", "UT"]) assert.equal(validation.isValidStateCode(code), true, code);
  for (const bad of ["dl", "XX", "Delhi", ""]) assert.equal(validation.isValidStateCode(bad), false, bad);
});

test("only formats the server accepts are offered as a photo", () => {
  assert.deepEqual([...validation.PHOTO_MIME_TYPES], ["image/jpeg", "image/png"]);
});

test("a date of birth is read on the local calendar", () => {
  const age = validation.deriveAgeFromDob("2026-09-30", new Date(2026, 9, 1, 0, 30));
  assert.equal(age.days, 1);
  assert.equal(age.years, 0);
});

test("the desk never computes today from the UTC date or prints an invented hospital", () => {
  for (const file of ["RegistrationForm.tsx", "PatientSearch.tsx"]) {
    assert.doesNotMatch(source(file), /toISOString\(\)\.slice\(0,\s*10\)/, file);
  }
  const card = source("PatientCardModal.tsx");
  assert.doesNotMatch(card, /HealthDoc Hospital/);
  assert.doesNotMatch(card, /setTimeout/);
  assert.match(card, /receptionist\.card\.facilityUnavailable/);
});
