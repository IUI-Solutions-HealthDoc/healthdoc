import assert from "node:assert/strict";
import test from "node:test";
import { compile, componentHarness, content, flush, nodes } from "./helpers/component-harness.mjs";
import { clinicalWrite } from "./helpers/clinical-write.mjs";

const definition = { id: "form", version: 1, code: "TEST", title: "Synthetic form", status: "published",
  fields_schema: [{ id: "checked", type: "checkbox", label: "Recorded answer" },
    { id: "measurement", type: "number", label: "Measurement", required: true }] };
const source = new URL("../src/features/forms/components/DynamicFormRenderer.tsx", import.meta.url);

test("dynamic form preserves boolean input and decimals, and refuses stale patient completion", async () => {
  const pending = [], completed = [];
  const h = componentHarness((runtime) => compile(source, {
    ...runtime, "lucide-react": Object.fromEntries(["AlertCircle", "CheckCircle2", "FileText", "Send"].map((name) => [name, "icon"])),
    "@/lib/useClinicalWrite": clinicalWrite(runtime),
    "../api": { submitForm: (payload) => new Promise((resolve) => pending.push({ payload, resolve })) },
  }).DynamicFormRenderer);
  const props = { formDef: definition, patientId: "A", onSuccess: (result) => completed.push(result) };
  let tree = h.render(props); h.effects();
  nodes(tree).find((n) => n.props.type === "checkbox").props.onChange({ target: { checked: true } });
  const numeric = nodes(tree).find((n) => n.props.type === "number");
  assert.equal(numeric.props.step, "any");
  numeric.props.onChange({ target: { value: "12.5" } });
  tree = h.render(props);
  assert.equal(nodes(tree).find((n) => n.props.type === "checkbox").props.checked, true);
  const submitting = nodes(tree).find((n) => n.type === "form").props.onSubmit({ preventDefault() {} });
  assert.deepEqual(pending[0].payload.form_data, { checked: true, measurement: 12.5 });
  tree = h.render({ ...props, patientId: "B" }); h.effects();
  assert.equal(nodes(tree).find((n) => n.props.type === "checkbox").props.checked, false);
  pending[0].resolve({ patient_id: "A", form_id: "form" });
  await submitting; await flush();
  tree = h.render({ ...props, patientId: "B" });
  assert.deepEqual(completed, []);
  assert.doesNotMatch(content(tree), /recorded successfully/);
});
