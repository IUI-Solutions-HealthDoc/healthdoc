import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const re = /"([^"]+)":\s*"/g;

function keys(file) {
  const s = new Set();
  const src = fs.readFileSync(path.join(root, file), "utf8");
  let m;
  while ((m = re.exec(src))) s.add(m[1]);
  return s;
}

const en = keys("src/lib/i18n/messages/en.ts");
const hi = keys("src/lib/i18n/messages/hi.ts");
const missing = [...en].filter((k) => !hi.has(k));
console.log("en", en.size, "hi", hi.size, "missing", missing.length);
console.log(missing.join("\n"));
