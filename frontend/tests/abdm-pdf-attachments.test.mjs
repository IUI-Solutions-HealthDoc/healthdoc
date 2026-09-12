import assert from "node:assert/strict";
import test from "node:test";
import { compile } from "./helpers/component-harness.mjs";
const { pdfBytes, embeddedPdfs } = compile(new URL("../src/features/doctor/abdm/pdfAttachments.ts", import.meta.url), {});
const data = btoa("%PDF-1.7\nSYNTHETIC\n%%EOF");

test("embedded Binary and DocumentReference PDFs are extracted without fetching URLs", () => {
  const bundle = { entry: [{ resource: { resourceType: "Binary", contentType: "application/pdf", data } },
    { resource: { resourceType: "DocumentReference", content: [{ attachment: { contentType: "application/pdf", data, title: "Duplicate" } }] } },
    { resource: { presentedForm: [{ contentType: "application/pdf", url: "https://untrusted.test/file" }] } }] };
  assert.equal(embeddedPdfs(bundle).length, 1);
  assert.equal(embeddedPdfs(bundle)[0].data, data);
  assert.equal(new TextDecoder().decode(pdfBytes(data)), atob(data));
});

test("oversized, non-PDF and malformed base64 bytes cannot reach the renderer", () => {
  for (const value of ["!invalid!", btoa("<script>bad</script>"), "A".repeat(1_400_000)]) assert.throws(() => pdfBytes(value));
});
