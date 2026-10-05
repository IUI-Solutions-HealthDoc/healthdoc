import type { HprDocument } from "./api/hpr";

/** HPR-059/060/069/075: PDF, PNG or JPEG, up to 5 MB, sent to HPR as base64. */
const TYPES: Record<string, HprDocument["file_type"]> = {
  "application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpeg",
};
export const HPR_DOCUMENT_ACCEPT = "application/pdf,image/png,image/jpeg";

export async function readHprDocument(file: File): Promise<HprDocument> {
  const fileType = TYPES[file.type];
  if (!fileType) throw new Error("Attach a PDF, PNG or JPEG file.");
  if (file.size > 5 * 1024 * 1024) throw new Error("The file must be at most 5 MB.");
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return { file_type: fileType, content: btoa(binary) };
}
