import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const enPath = path.join(root, "src/lib/i18n/messages/en.ts");
const hiPath = path.join(root, "src/lib/i18n/messages/hi.ts");
const overridesPath = path.join(root, "scripts/hi-overrides.json");

const keyRe = /"([^"]+)":\s*"/g;

function extractKeys(src) {
  const s = new Set();
  let m;
  while ((m = keyRe.exec(src))) s.add(m[1]);
  return s;
}

function extractValue(src, key) {
  const esc = key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const re = new RegExp(
    `"${esc}":\\s*(?:\\n\\s*)?"((?:\\\\.|[^"\\\\])*)"`,
  );
  const m = re.exec(src);
  if (!m) return null;
  return m[1].replace(/\\"/g, '"').replace(/\\\\/g, "\\");
}

const enSrc = fs.readFileSync(enPath, "utf8");
const hiSrc = fs.readFileSync(hiPath, "utf8");
const enKeys = extractKeys(enSrc);
const hiKeys = extractKeys(hiSrc);
const overrides = fs.existsSync(overridesPath)
  ? JSON.parse(fs.readFileSync(overridesPath, "utf8"))
  : {};

const missing = [...enKeys].filter((k) => !hiKeys.has(k));
if (missing.length === 0) {
  console.log("hi.ts already has all en keys");
  process.exit(0);
}

const lines = missing.map((key) => {
  const val = overrides[key] ?? extractValue(enSrc, key) ?? key;
  const escaped = val.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  if (val.includes("\n")) {
    return `  "${key}":\n    "${escaped}",`;
  }
  return `  "${key}": "${escaped}",`;
});

let out = hiSrc;
const marker = "} as const satisfies Record<MessageKey, string>;";
const idx = out.indexOf(marker);
if (idx === -1) throw new Error("hi.ts marker not found");
out = `${out.slice(0, idx)}${lines.join("\n")}\n${out.slice(idx)}`;
fs.writeFileSync(hiPath, out);
console.log("Added", missing.length, "keys to hi.ts");
