/**
 * A driving-licence photo as the ABDM enrolment expects it: plain base64.
 *
 * Camera photos run to several megabytes; the server accepts two per side.
 * The longest edge is cut to 1600 px and re-encoded as JPEG, which keeps the
 * printed text legible for NHA's verifier at a few hundred kilobytes.
 */
const MAX_EDGE = 1600;

export async function prepareLicencePhoto(file: File): Promise<string> {
  if (!/^image\/(jpeg|png)$/.test(file.type)) {
    throw new Error("Choose a JPEG or PNG photo of the licence.");
  }
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d")?.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  const dataUrl = canvas.toDataURL("image/jpeg", 0.85);
  return dataUrl.slice(dataUrl.indexOf(",") + 1);
}
