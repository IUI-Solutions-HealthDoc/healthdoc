import assert from "node:assert/strict";
import test from "node:test";
import { compile, componentHarness, content, flush, nodes } from "./helpers/component-harness.mjs";

test("mixed record types leave the browser in one explicit document-selection request", async () => {
  const writes = [];
  const documents = [
    { id: "doc-a", reference: "A", display: "Synthetic prescription", hi_type: "Prescription" },
    { id: "doc-b", reference: "B", display: "Synthetic wellness", hi_type: "WellnessRecord" },
  ];
  const ui = componentHarness((runtime) => compile(new URL("../src/features/doctor/abdm/DocumentSharing.tsx", import.meta.url), {
    ...runtime,
    "@/lib/api": {
      newIdempotencyKey: () => "test-batch-key",
      getUserFacingError: (_, fallback) => fallback,
      api: async (path, options) => {
        if (options?.method === "POST") { writes.push({ path, ...options }); return []; }
        return path.includes("care-contexts") ? documents : [];
      },
    },
  }).DocumentSharing);
  let tree = ui.render({ patientId: "patient-a", verified: true });
  ui.effects(); await flush(); tree = ui.render({ patientId: "patient-a", verified: true });
  for (const checkbox of nodes(tree).filter((n) => n.type === "input")) checkbox.props.onChange({ target: { checked: true } });
  tree = ui.render({ patientId: "patient-a", verified: true });
  nodes(tree).find((n) => n.type === "button" && content(n) === "Link selected documents").props.onClick();
  await flush();
  assert.equal(writes.length, 1);
  assert.equal(writes[0].path, "/abdm/hip/patients/patient-a/links");
  assert.deepEqual(JSON.parse(writes[0].body), { context_ids: ["doc-a", "doc-b"] });
  assert.equal(writes[0].idempotencyKey, "test-batch-key");
  assert.match(content(ui.render({ patientId: "patient-a", verified: true })), /grouped by record type in one request/);
});
