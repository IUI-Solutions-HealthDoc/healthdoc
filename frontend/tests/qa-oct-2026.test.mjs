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

test("the seeded dev ward and facility ids pass the admission and discharge forms", async () => {
  // QA 10 Oct 2026: 00000000-0000-0000-0000-000000000104 is not an RFC 4122 UUID,
  // z.string().uuid() refused it, and no patient could be admitted in any make setup.
  const { z } = await import("zod");
  const admission = compile(source("features/ipd/components/AdmissionForm/validation.ts"), { zod: { z } });
  const seeded = {
    visit_id: "00000000-0000-0000-0000-000000000901",
    ward_id: "00000000-0000-0000-0000-000000000104",
    bed_id: "00000000-0000-0000-0000-000000000105",
    admitted_at: "2026-10-13T10:00",
  };
  assert.equal(admission.addAdmissionSchema.safeParse(seeded).success, true);
  assert.equal(admission.addAdmissionSchema.safeParse({ ...seeded, ward_id: "" }).success, false);
});
