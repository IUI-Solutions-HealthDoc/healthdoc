import assert from "node:assert/strict";
import test from "node:test";
import { compile } from "./helpers/component-harness.mjs";

/** ABDM refuses a licence photo of 150 KB or more (live, 3 Oct 2026). The
 * canvas is a stub whose JPEG size follows its area and quality. */
const { prepareLicencePhoto, decodedBytes, MAX_PHOTO_BYTES } = compile(
  new URL("../src/features/receptionist/licencePhoto.ts", import.meta.url), {},
);

function camera(width, height, bytesPerPixelAtFullQuality) {
  const tried = [];
  globalThis.createImageBitmap = async () => ({ width, height, close() {} });
  globalThis.document = {
    createElement: () => ({
      width: 0, height: 0,
      getContext: () => ({ drawImage() {} }),
      toDataURL(type, quality) {
        const bytes = Math.round(this.width * this.height * bytesPerPixelAtFullQuality * quality);
        tried.push({ edge: Math.max(this.width, this.height), quality, bytes });
        return `data:${type};base64,${"A".repeat(Math.ceil((bytes * 4) / 3))}`;
      },
    }),
  };
  return tried;
}

test("a small photo goes as it is, at the first quality", async () => {
  const tried = camera(800, 500, 0.2);
  const encoded = await prepareLicencePhoto({ type: "image/jpeg" });
  assert.equal(tried.length, 1);
  assert.ok(decodedBytes(encoded) < MAX_PHOTO_BYTES);
});

test("a camera photo is re-encoded smaller until it is under ABDM's limit", async () => {
  const tried = camera(4000, 3000, 0.4);
  const encoded = await prepareLicencePhoto({ type: "image/jpeg" });
  assert.ok(decodedBytes(encoded) < MAX_PHOTO_BYTES);
  assert.ok(MAX_PHOTO_BYTES < 150_000, "a margin under ABDM's 150 KB");
  assert.ok(tried.length > 1 && tried.at(-1).edge < 1600, "quality first, then size");
});

test("a photo that cannot fit asks the desk to retake it", async () => {
  camera(4000, 3000, 50);
  await assert.rejects(prepareLicencePhoto({ type: "image/jpeg" }), /150 KB limit/);
});

test("only JPEG and PNG are taken", async () => {
  await assert.rejects(prepareLicencePhoto({ type: "image/heic" }), /JPEG or PNG/);
});
