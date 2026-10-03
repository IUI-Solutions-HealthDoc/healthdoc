/**
 * A driving-licence photo as the ABDM enrolment expects it: plain base64.
 *
 * ABDM refuses a licence photo of 150 KB or more ("Please upload a document of
 * size less than 150KB", live, 3 Oct 2026). Camera photos run to several
 * megabytes, so the photo is re-encoded as JPEG, first at lower quality and
 * then smaller, until it fits with a margin. Text stays legible down to the
 * smallest edge tried; below that the desk is asked to retake the photo.
 */
export const MAX_PHOTO_BYTES = 140_000;
const EDGES = [1600, 1280, 1024, 800, 640];
const QUALITIES = [0.85, 0.7, 0.55, 0.4];

/** Bytes a base64 string decodes to. */
export function decodedBytes(encoded: string): number {
  const padding = encoded.endsWith("==") ? 2 : encoded.endsWith("=") ? 1 : 0;
  return Math.floor((encoded.length * 3) / 4) - padding;
}

export async function prepareLicencePhoto(file: File): Promise<string> {
  if (!/^image\/(jpeg|png)$/.test(file.type)) {
    throw new Error("Choose a JPEG or PNG photo of the licence.");
  }
  const bitmap = await createImageBitmap(file);
  try {
    const canvas = document.createElement("canvas");
    for (const edge of EDGES) {
      const scale = Math.min(1, edge / Math.max(bitmap.width, bitmap.height));
      canvas.width = Math.round(bitmap.width * scale);
      canvas.height = Math.round(bitmap.height * scale);
      canvas.getContext("2d")?.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      for (const quality of QUALITIES) {
        const dataUrl = canvas.toDataURL("image/jpeg", quality);
        const encoded = dataUrl.slice(dataUrl.indexOf(",") + 1);
        if (decodedBytes(encoded) < MAX_PHOTO_BYTES) return encoded;
      }
    }
  } finally {
    bitmap.close();
  }
  throw new Error("This photo cannot be made smaller than ABDM's 150 KB limit. Retake it closer to the licence, with less background.");
}
