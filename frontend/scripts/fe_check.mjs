#!/usr/bin/env node
/**
 * HealthDoc frontend convention checker — the mirror of backend/scripts/pr_check.py.
 *
 *   node scripts/fe_check.mjs            # changed files vs origin/staging
 *   node scripts/fe_check.mjs app/...    # specific files
 *   node scripts/fe_check.mjs --all      # everything under app/, lib/, components/
 *
 * Exit 1 on any BLOCKER. Every rule cites the contract it enforces.
 * Use "// fe-check: ignore" on a line with a written reason in the PR.
 */
import { readFileSync, existsSync, readdirSync, statSync } from "node:fs";
import { execSync } from "node:child_process";
import path from "node:path";

const BLOCK = "BLOCKER";
const WARN = "WARN";
const findings = [];

const add = (sev, rule, file, line, msg, ref) =>
  findings.push({ sev, rule, file, line, msg, ref });

const RULES = [
  {
    rule: "RAW-FETCH",
    sev: BLOCK,
    test: (l) => /\bfetch\s*\(\s*[`'"]\/?api\//.test(l),
    msg: "Raw fetch() to the API — bypasses the envelope, auth header, idempotency and error mapping.",
    ref: "schema §4.1: all calls go through lib/api.ts",
    skipFiles: ["lib/api.ts"],
  },
  {
    rule: "TOKEN-STORAGE",
    sev: BLOCK,
    test: (l) =>
      /(localStorage|sessionStorage)\s*\.\s*(setItem|getItem)\s*\(\s*[`'"][^`'"]*(token|jwt|auth|access)/i.test(l),
    msg: "Access token in web storage is readable by any injected script — a stolen token is full patient access.",
    ref: "lib/api.ts: token is held in memory only",
  },
  {
    rule: "MONEY-FLOAT",
    sev: BLOCK,
    test: (l) =>
      /(parseFloat|Number|\+\s*)\s*\(?\s*[\w.]*(amount|price|net_amount|gross_amount|total|paid)/i.test(l) &&
      !/formatMoney/.test(l),
    msg: "Money parsed as a number — paise are silently lost. Amounts arrive as strings.",
    ref: "schema §4.2 + lib/api.ts formatMoney()",
  },
  {
    rule: "BIZ-ID-IN-URL",
    sev: BLOCK,
    test: (l) =>
      /api\s*[<(][^)]*[`'"][^`'"]*\/(patients|invoices|orders|visits)\/\$\{[^}]*(uhid|invoice_number|order_number|token_display)/i.test(l),
    msg: "Business identifier used as a URL path param — routes take UUIDs only.",
    ref: "schema §4.2: every {id} path param is a UUID",
  },
  {
    rule: "PII-ON-DISPLAY",
    sev: BLOCK,
    test: (l, file) =>
      /queue-display|\/display\//.test(file) &&
      /(full_name|patient_name|uhid|mobile|abha)/i.test(l),
    msg: "Patient identifier rendered on the public queue display — it shows token, doctor and room only.",
    ref: "schema §4A.7 / notification payload PII rule",
  },
  {
    rule: "HARDCODED-URL",
    sev: BLOCK,
    test: (l) => /[`'"]https?:\/\/(localhost|127\.0\.0\.1|[\d.]+)(:\d+)?\/api/i.test(l),
    msg: "Hardcoded API host — breaks at every facility. Use NEXT_PUBLIC_API_BASE_URL.",
    ref: "dev-setup.md",
  },
  {
    rule: "UTC-DISPLAY",
    sev: WARN,
    test: (l) =>
      /toLocaleString\(\)|toLocaleDateString\(\)|toLocaleTimeString\(\)/.test(l) &&
      !/timeZone/.test(l),
    msg: "Date formatted without an explicit timeZone — renders in the browser's zone, not the facility's.",
    ref: "lib/api.ts formatDateTime()",
  },
  {
    rule: "NO-CAPABILITY-GATE",
    sev: WARN,
    test: (l, file) =>
      /(app\/(pharmacy|lab|radiology|ot|blood-bank))/.test(file) &&
      /export default function/.test(l),
    msg: "Optional-module screen: confirm it is gated by /facility/capabilities and handles 409 module_disabled.",
    ref: "schema §Module toggle behavior rule 6",
    once: true,
  },
  {
    rule: "MISSING-IDEMPOTENCY",
    sev: WARN,
    test: (l) => /method:\s*["'`]POST["'`]/.test(l),
    msg: "POST via api(): pass idempotencyKey so a retry cannot create a duplicate.",
    ref: "schema §4A.1",
    needsAbsent: /idempotencyKey/,
  },
];

function checkFile(file) {
  if (!existsSync(file)) return;
  const rel = file.replace(/\\/g, "/");
  if (/node_modules|\.next|dist|next-env\.d\.ts/.test(rel)) return;
  const src = readFileSync(file, "utf8");
  const lines = src.split("\n");
  const seen = new Set();

  lines.forEach((raw, i) => {
    const line = raw;
    if (line.includes("fe-check: ignore")) return;
    if (/^\s*(\/\/|\*|\/\*)/.test(line)) return; // comments

    for (const r of RULES) {
      if (r.skipFiles?.some((s) => rel.endsWith(s))) continue;
      if (r.once && seen.has(r.rule)) continue;
      if (!r.test(line, rel)) continue;
      if (r.needsAbsent && r.needsAbsent.test(src)) continue;
      seen.add(r.rule);
      add(r.sev, r.rule, rel, i + 1, r.msg, r.ref);
    }
  });
}

function walk(dir, out = []) {
  if (!existsSync(dir)) return out;
  for (const e of readdirSync(dir)) {
    const p = path.join(dir, e);
    if (/node_modules|\.next|dist/.test(p)) continue;
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.(ts|tsx|js|jsx)$/.test(p)) out.push(p);
  }
  return out;
}

function changedFiles() {
  try {
    execSync("git fetch --no-tags --depth=50 origin staging", { stdio: "ignore" });
    const base =
      execSync("git merge-base HEAD origin/staging").toString().trim() || "HEAD~1";
    return execSync(`git diff --name-only ${base} HEAD`)
      .toString()
      .split("\n")
      .filter((f) => /^frontend\/.*\.(ts|tsx|js|jsx)$/.test(f))
      .map((f) => f.replace(/^frontend\//, ""));
  } catch {
    return [];
  }
}

const args = process.argv.slice(2);
let files;
if (args[0] === "--all") files = [...walk("app"), ...walk("lib"), ...walk("components")];
else if (args.length) files = args;
else files = changedFiles();

files.forEach(checkFile);

const blockers = findings.filter((f) => f.sev === BLOCK);
const warns = findings.filter((f) => f.sev === WARN);
console.log(
  `FE CHECK — ${files.length} file(s), ${blockers.length} blocker(s), ${warns.length} warning(s)\n`,
);
for (const f of [...blockers, ...warns]) {
  console.log(`  ${f.sev === BLOCK ? "✗" : "!"} [${f.rule}] ${f.file}:${f.line}`);
  console.log(`      ${f.msg}`);
  console.log(`      → ${f.ref}`);
}
if (!findings.length) console.log("  ✓ clean");
process.exit(blockers.length ? 1 : 0);
