export type EmbeddedPdf = { title: string; data: string };
const MAX_PDF_BYTES = 1024 * 1024;

export function pdfBytes(data: string): Uint8Array {
  if (data.length > 4 * Math.ceil(MAX_PDF_BYTES / 3) || !/^[A-Za-z0-9+/]*={0,2}$/.test(data)) throw new Error("Invalid PDF attachment");
  const decoded = atob(data);
  if (!decoded.startsWith("%PDF-") || decoded.length > MAX_PDF_BYTES) throw new Error("Invalid PDF attachment");
  return Uint8Array.from(decoded, (char) => char.charCodeAt(0));
}

/** Backend already verified document membership and consent. Never fetch URLs. */
export function embeddedPdfs(bundle: Record<string, unknown>): EmbeddedPdf[] {
  const output: EmbeddedPdf[] = [];
  function walk(value: unknown, depth: number) {
    if (!value || typeof value !== "object" || depth > 24) return;
    if (Array.isArray(value)) { value.forEach((item) => walk(item, depth + 1)); return; }
    const node = value as Record<string, unknown>;
    if (node.contentType === "application/pdf" && typeof node.data === "string") {
      pdfBytes(node.data);
      if (!output.some((p) => p.data === node.data)) output.push({ title: typeof node.title === "string" ? node.title : `PDF attachment ${output.length + 1}`, data: node.data });
    }
    Object.values(node).forEach((item) => walk(item, depth + 1));
  }
  walk(bundle, 0);
  return output;
}
