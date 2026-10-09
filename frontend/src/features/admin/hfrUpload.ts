/** A facility photo or address proof for HFR: PNG or JPEG, at most 5 MB (HFR-027/028/030). */
const MAX_BYTES = 5 * 1024 * 1024;

export function readHfrUpload(file: File): Promise<{ name: string; content: string }> {
  if (!/^image\/(png|jpeg)$/.test(file.type)) {
    return Promise.reject(new Error("Choose a PNG or JPEG image."));
  }
  if (file.size > MAX_BYTES) return Promise.reject(new Error("The image must be at most 5 MB."));
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("The image could not be read."));
    reader.onload = () => {
      const url = String(reader.result ?? "");
      resolve({ name: file.name, content: url.slice(url.indexOf(",") + 1) });
    };
    reader.readAsDataURL(file);
  });
}
