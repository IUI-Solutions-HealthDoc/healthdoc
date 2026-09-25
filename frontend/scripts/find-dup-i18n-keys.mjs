import { readFileSync } from "node:fs";

for (const f of ["en", "hi"]) {
  const src = readFileSync(`src/lib/i18n/messages/${f}.ts`, "utf8");
  const counts = new Map();
  const re = /"([^"]+)":/g;
  let m;
  while ((m = re.exec(src))) counts.set(m[1], (counts.get(m[1]) || 0) + 1);
  const dups = [...counts].filter(([, c]) => c > 1);
  console.log(f, dups.length);
  for (const [k, c] of dups) console.log(c, k);
}
