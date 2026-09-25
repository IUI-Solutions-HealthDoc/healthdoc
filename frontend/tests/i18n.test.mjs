/**
 * Pure i18n helpers tested without a TS loader.
 * Catalogue parity is enforced by `hi satisfies Record<MessageKey, string>` at compile time.
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";
import { compile } from "./helpers/component-harness.mjs";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");

const en = compile(new URL("../src/lib/i18n/messages/en.ts", import.meta.url), {}).en;
const hi = compile(new URL("../src/lib/i18n/messages/hi.ts", import.meta.url), {}).hi;
const { localizeField, translate } = compile(new URL("../src/lib/i18n/index.ts", import.meta.url), {
  react: { useCallback: (callback) => callback, useEffect() {}, useSyncExternalStore: () => "en" },
  "./messages/en": { en },
  "./messages/hi": { hi },
});

function extractKeys(source) {
  const keys = [];
  const re = /"([^"]+)":\s*"/g;
  let m;
  while ((m = re.exec(source))) keys.push(m[1]);
  return keys;
}

describe("localizeField", () => {
  it("falls back to English when Hindi is null or blank", () => {
    assert.equal(localizeField("General Medicine", null, "hi"), "General Medicine");
    assert.equal(localizeField("General Medicine", "  ", "hi"), "General Medicine");
    assert.equal(localizeField("General Medicine", "सामान्य चिकित्सा", "hi"), "सामान्य चिकित्सा");
    assert.equal(localizeField("General Medicine", "सामान्य चिकित्सा", "en"), "General Medicine");
  });
  it("uses the actual catalogue and interpolates variables", () => {
    assert.equal(translate("common.search", "en"), en["common.search"]);
    assert.equal(translate("common.search", "hi"), hi["common.search"]);
    assert.equal(translate("admin.abdm.jobs.attempts", "en", { count: 3 }), "3 attempt(s)");
  });
});

describe("message catalogues", () => {
  it("en and hi define the same keys", () => {
    const enSrc = readFileSync(path.join(root, "src/lib/i18n/messages/en.ts"), "utf8");
    const hiSrc = readFileSync(path.join(root, "src/lib/i18n/messages/hi.ts"), "utf8");
    const enKeys = new Set(extractKeys(enSrc));
    const hiKeys = new Set(extractKeys(hiSrc));
    const missingInHi = [...enKeys].filter((k) => !hiKeys.has(k));
    const extraInHi = [...hiKeys].filter((k) => !enKeys.has(k));
    assert.deepEqual(missingInHi, [], `Hindi missing keys: ${missingInHi.join(", ")}`);
    assert.deepEqual(extraInHi, [], `Hindi extra keys: ${extraInHi.join(", ")}`);
    assert.ok(enKeys.size > 50, "expected a substantial catalogue");
  });
});
