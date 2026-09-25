import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const enPath = path.join(root, "src/lib/i18n/messages/en.ts");
const hiPath = path.join(root, "src/lib/i18n/messages/hi.ts");

/** @type {Record<string, [string, string]>} */
const pairs = JSON.parse(
  fs.readFileSync(path.join(root, "scripts/phase3-i18n-pairs.json"), "utf8"),
);

function insertKeys(filePath, marker) {
  let src = fs.readFileSync(filePath, "utf8");
  const markerIdx = src.indexOf(marker);
  if (markerIdx === -1) throw new Error(`marker not found in ${filePath}: ${marker}`);
  const isHi = filePath.includes("hi.ts");
  const lines = [];
  for (const [key, [enVal, hiVal]] of Object.entries(pairs)) {
    const val = isHi ? hiVal : enVal;
    const escaped = val.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
    if (val.includes("\n")) {
      lines.push(`  "${key}":\n    "${escaped}",`);
    } else {
      lines.push(`  "${key}": "${escaped}",`);
    }
  }
  const block = `${lines.join("\n")}\n  `;
  src = src.slice(0, markerIdx) + block + src.slice(markerIdx);
  fs.writeFileSync(filePath, src);
}

insertKeys(enPath, '"audit.title"');
insertKeys(hiPath, '"audit.title"');
console.log("Inserted", Object.keys(pairs).length, "keys");
