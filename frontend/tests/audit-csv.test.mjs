import assert from "node:assert/strict";
import test from "node:test";

import { toCsv } from "../src/features/audit-viewer/lib/toCsv.mjs";

/**
 * The Access log, File access and Integrity tabs have no server export
 * endpoint, so their CSV is built in the browser from the rows on screen.
 * Escaping is therefore the whole job: audit rows carry free text — reasons,
 * justifications, user agents — and a naive join(",") shifts every later
 * column into the wrong header on exactly the rows an investigator cares
 * about. A corrupted evidence file that opens cleanly is worse than one that
 * fails to open.
 */

test("a comma in a field does not shift the following columns", () => {
  const csv = toCsv([{ action: "view", reason: "Reviewed chart, then exported", role: "auditor" }]);
  const [, row] = csv.split("\r\n");
  assert.equal(row, 'view,"Reviewed chart, then exported",auditor');
});

test("an inner quote is doubled, per RFC 4180", () => {
  const csv = toCsv([{ reason: 'Patient said "no"' }]);
  assert.equal(csv.split("\r\n")[1], '"Patient said ""no"""');
});

test("a newline inside a field stays inside its quoted cell", () => {
  const csv = toCsv([{ reason: "line one\nline two" }]);
  // Two data lines' worth of text, but one logical row: the quote holds it.
  assert.ok(csv.includes('"line one\nline two"'));
  assert.equal(csv.split("\r\n").length, 2);
});

test("headers are the union of all rows, not just the first", () => {
  // Audit rows are sparse — an entry with no patient is missing the key
  // entirely. Taking row zero's keys drops columns later rows populate.
  const csv = toCsv([{ id: "1" }, { id: "2", patient_id: "p9" }]);
  assert.equal(csv.split("\r\n")[0], "id,patient_id");
  assert.equal(csv.split("\r\n")[2], "2,p9");
});

test("null and undefined become empty cells, not the words", () => {
  const csv = toCsv([{ a: null, b: undefined, c: "x" }]);
  assert.equal(csv.split("\r\n")[1], ",,x");
  assert.doesNotMatch(csv, /null|undefined/);
});

test("an object value is serialised rather than becoming [object Object]", () => {
  const csv = toCsv([{ old_value: { status: "active" } }]);
  assert.match(csv, /status/);
  assert.doesNotMatch(csv, /\[object Object\]/);
});

test("no rows produces no file rather than a headers-only one", () => {
  // The dashboard refuses to download this — an empty evidence export that
  // reports success is how an inspection receives nothing.
  assert.equal(toCsv([]), "");
});
