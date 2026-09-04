import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

/**
 * The audit Action dropdown is built from a TypeScript list; the rows it
 * filters are written from a Python enum. Nothing connected the two, so they
 * drifted:
 *
 *   - the dropdown offered "merge", which the backend has never written —
 *     real merges are uhid_merge / thid_merge / thid_unmerge, so filtering for
 *     Merge returned nothing and read as "no merges happened"
 *   - it offered "delete_attempt", also never written
 *   - it omitted nine actions the backend DOES write, hiding real records
 *
 * Both directions matter, so both are asserted. Parsed from the files rather
 * than restated here: a copy of the list in this test would be a third thing
 * to drift.
 */

const py = readFileSync(new URL("../../backend/app/audit/actions.py", import.meta.url), "utf8");
const ts = readFileSync(new URL("../src/features/audit-viewer/types.ts", import.meta.url), "utf8");
const constants = readFileSync(
  new URL("../src/features/audit-viewer/constants.ts", import.meta.url), "utf8");

/** Enum members are `NAME = "value"` inside class AuditAction. */
const backend = new Set([...py.matchAll(/^\s+[A-Z_]+ = "([a-z_]+)"/gm)].map((m) => m[1]));

const typeBlock = ts.slice(ts.indexOf("export type AuditAction ="));
const frontendType = new Set(
  [...typeBlock.slice(0, typeBlock.indexOf(";")).matchAll(/"([a-z_]+)"/g)].map((m) => m[1]));

const listStart = constants.indexOf("export const COMMON_AUDIT_ACTIONS");
const dropdown = new Set(
  [...constants.slice(listStart, constants.indexOf("];", listStart)).matchAll(/"([a-z_]+)"/g)]
    .map((m) => m[1]));

const diff = (a, b) => [...a].filter((x) => !b.has(x)).sort();

test("the enum is not empty — the parse itself has to be working", () => {
  // Without this, a regex that matched nothing would make every assertion
  // below pass vacuously, which is the failure mode this repo keeps finding.
  assert.ok(backend.size >= 10, `parsed only ${backend.size} actions from actions.py`);
});

test("the AuditAction type matches the backend enum exactly", () => {
  assert.deepEqual(diff(backend, frontendType), [], "in the enum, missing from the TS type");
  assert.deepEqual(diff(frontendType, backend), [], "in the TS type, not a real backend action");
});

test("the Action dropdown offers every action the backend can write", () => {
  assert.deepEqual(diff(backend, dropdown), [], "backend writes these but the dropdown hides them");
  assert.deepEqual(diff(dropdown, backend), [], "dropdown offers these but nothing writes them");
});

test('"merge" is not offered, because nothing writes it', () => {
  // The specific regression. Named so a future reader sees the reason.
  assert.ok(!dropdown.has("merge"));
  assert.ok(["uhid_merge", "thid_merge", "thid_unmerge"].every((a) => dropdown.has(a)));
});
