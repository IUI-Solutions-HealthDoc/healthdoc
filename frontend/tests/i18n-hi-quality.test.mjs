/**
 * Fails when Hindi catalogue values are still identical to English for
 * product chrome keys. Intentional same-language tokens (UHID, ABDM, OT, …)
 * are allowlisted.
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");

const CHROME_PREFIXES = [
  "common.",
  "nav.",
  "sidebar.",
  "area.",
  "role.",
  "field.",
  "patient.",
  "forms.",
  "receptionist.",
  "startVisit.",
  "doctor.",
  "nurse.",
  "ipd.",
  "emergency.",
  "lab.",
  "radiology.",
  "pharmacy.",
  "billing.",
  "inventory.",
  "reports.",
  "patientPortal.",
  "audit.",
  "admin.",
  "hod.",
  "supervisor.",
  "consent.",
  "bloodBank.",
  "immunization.",
  "ot.",
  "programs.",
  "maintenance.",
  "auth.",
  "priority.",
  "visitType.",
];

/** Strings that are correctly identical in EN and HI (acronyms / units). */
const ALLOW_SAME = new Set([
  "UHID",
  "THID",
  "ABHA",
  "ABDM",
  "OTP",
  "OT",
  "OPD",
  "IPD",
  "CSV",
  "PDF",
  "QR",
  "eMAR",
  "MIS",
  "KPI",
  "NHA",
  "HFR",
  "mL",
  "ml",
  "°C",
  "SpO₂",
  "SpO2",
  "BP",
  "ID",
  "API",
  "UI",
  "SSO",
]);

function extractEntries(source) {
  const entries = new Map();
  const re = /"([^"]+)":\s*"((?:\\.|[^"\\])*)"/g;
  let m;
  while ((m = re.exec(source))) {
    entries.set(m[1], m[2].replace(/\\"/g, '"').replace(/\\n/g, "\n"));
  }
  return entries;
}

function isChromeKey(key) {
  return CHROME_PREFIXES.some((p) => key.startsWith(p));
}

function isAllowlisted(value) {
  const trimmed = value.trim();
  if (!trimmed) return true;
  if (ALLOW_SAME.has(trimmed)) return true;
  // Pure acronym / code tokens and short technical labels
  if (/^[A-Z0-9][A-Z0-9_\-./+]{0,12}$/.test(trimmed)) return true;
  // Contains Devanagari already → fine even if partially bilingual
  if (/[\u0900-\u097F]/.test(trimmed)) return true;
  return false;
}

describe("Hindi catalogue quality", () => {
  it("chrome keys differ from English unless allowlisted", () => {
    const en = extractEntries(readFileSync(path.join(root, "src/lib/i18n/messages/en.ts"), "utf8"));
    const hi = extractEntries(readFileSync(path.join(root, "src/lib/i18n/messages/hi.ts"), "utf8"));
    const same = [];
    for (const [key, enValue] of en) {
      if (!isChromeKey(key)) continue;
      const hiValue = hi.get(key);
      if (hiValue === undefined) continue;
      if (hiValue === enValue && !isAllowlisted(enValue)) {
        same.push(key);
      }
    }
    assert.deepEqual(
      same,
      [],
      `Hindi still equals English for ${same.length} chrome keys (first 40): ${same.slice(0, 40).join(", ")}`,
    );
  });
});
