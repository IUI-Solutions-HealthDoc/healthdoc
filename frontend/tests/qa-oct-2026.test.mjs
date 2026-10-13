import assert from "node:assert/strict";
import test from "node:test";
import { compile } from "./helpers/component-harness.mjs";

const source = (path) => new URL(`../src/${path}`, import.meta.url);

test("an unknown age is never shown as 0 or '?'", () => {
  // QA 10 Oct 2026: "?y" on the dashboard, "0 yrs" (a newborn) in the consultation header.
  const age = compile(source("lib/format-age.ts"), {});
  assert.equal(age.formatAge(null), "Age unknown");
  assert.equal(age.formatAge(undefined), "Age unknown");
  assert.equal(age.formatAge(0), "0 yrs");
  assert.equal(age.formatAgeSex(null, "other"), "Age unknown · Other");
  assert.equal(age.formatAgeSex(34, "male"), "34 yrs · Male");
  assert.equal(age.formatAgeSexShort(null, "female"), "Age unknown/F");
  assert.equal(age.formatAgeSexShort(3, "male"), "3y/M");
});
