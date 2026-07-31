#!/usr/bin/env python3
"""HealthDoc PR checker — static review against the binding conventions.

Usage:
  python scripts/pr_check.py                 # check changed files vs origin/staging
  python scripts/pr_check.py path/to/file.py [more...]
  python scripts/pr_check.py --all           # whole backend

Exit 1 on any BLOCKER. Designed to run in CI so reviewers only read what the
machine can't judge. Every rule cites the convention it enforces.
"""
from __future__ import annotations
import ast, pathlib, re, subprocess, sys

BLOCK, WARN = "BLOCKER", "WARN"
MIXIN_COLS = {"id", "created_at", "updated_at", "created_by", "updated_by"}
MONEY_HINTS = ("amount", "price", "rate", "total", "gross", "net", "discount", "mrp")
ENUM_COL_HINTS = ("status", "type", "mode", "priority", "category", "path", "channel",
                  "sex", "effect", "setting", "action")

class Finding:
    def __init__(self, sev, rule, file, line, msg, ref):
        self.sev, self.rule, self.file, self.line, self.msg, self.ref = sev, rule, file, line, msg, ref
    def __str__(self):
        tag = "✗" if self.sev == BLOCK else "!"
        return f"  {tag} [{self.rule}] {self.file}:{self.line}\n      {self.msg}\n      → {self.ref}"

SKIP_PATTERNS = ("__init__.py", "/tests/", "\\tests\\", "scripts/pr_check.py")

def check_file(path: pathlib.Path) -> list[Finding]:
    rel_norm = str(path).replace("\\", "/")
    # Tests deliberately contain anti-patterns (they prove the patterns are wrong);
    # __init__.py is never a migration. Use "# pr-check: ignore" for a one-off exception.
    if any(sk.replace("\\", "/") in rel_norm or rel_norm.endswith(sk) for sk in SKIP_PATTERNS):
        return []
    try:
        src = path.read_text()
    except Exception:
        return []
    f: list[Finding] = []
    rel = str(path)
    lines = src.splitlines()
    is_model = "models.py" in rel or "migrations/versions/" in rel.replace("\\", "/")
    is_migration = "migrations/versions/" in rel.replace("\\", "/")

    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        if "pr-check: ignore" in ln:
            continue

        # --- race conditions on identifier allocation -------------------------
        if re.search(r"\bmax\s*\(", ln, re.I) and re.search(r"\+\s*1|\bfunc\.max\b", ln, re.I):
            f.append(Finding(BLOCK, "SEQ-RACE", rel, i,
                "MAX(col)+1 allocation races under concurrency (duplicate UHID/token/receipt).",
                "conventions §2.2: use a counters row with SELECT … FOR UPDATE"))

        # --- timezone / business date ----------------------------------------
        if re.search(r"CURRENT_DATE|now\(\)::date|utcnow\(\)\.date\(\)|datetime\.now\(\)\.date\(\)", ln):
            f.append(Finding(BLOCK, "TZ-DATE", rel, i,
                "Business date computed in UTC/naive — 00:00–05:30 IST resolves to YESTERDAY.",
                "schema §3: (now() AT TIME ZONE facilities.timezone)::date"))

        # --- money as float ---------------------------------------------------
        if re.search(r"\b(Float|REAL|DOUBLE|float)\b", ln) and any(h in ln.lower() for h in MONEY_HINTS):
            f.append(Finding(BLOCK, "MONEY-FLOAT", rel, i,
                "Money must never be float — paise drift is unrecoverable.",
                "conventions §1.6: NUMERIC(12,2)"))

        # --- Aadhaar plaintext -------------------------------------------------
        if re.search(r"aadhaar", ln, re.I) and re.search(r"print\(|logger|logging|f\"|'\)", ln) \
           and not re.search(r"blind_index|encrypted|hash|#", ln, re.I):
            f.append(Finding(BLOCK, "PII-AADHAAR", rel, i,
                "Possible Aadhaar in a log/plaintext path.",
                "conventions §1.7 / §8: encrypted + blind index only, never logged"))

        # --- config discipline --------------------------------------------------
        if re.search(r"os\.environ|os\.getenv", ln) and "common/config.py" not in rel:
            f.append(Finding(WARN, "CONFIG", rel, i,
                "Reads env directly; every setting belongs in common/config.py.",
                "architecture §4: modules never read os.environ"))

        # --- enum column width + inline strings ---------------------------------
        if is_model and re.search(r"String\((\d{1,2})\)", ln):
            width = int(re.search(r"String\((\d{1,2})\)", ln).group(1))
            if width < 50 and any(h in ln.lower() for h in ENUM_COL_HINTS):
                f.append(Finding(BLOCK, "ENUM-WIDTH", rel, i,
                    f"Enum-backed column is String({width}); rule is varchar(50).",
                    "schema §3 blanket rule (v3.4.1)"))

        # --- direct Mongo write in a request path --------------------------------
        if re.search(r"get_mongo\(\)|motor|AsyncIOMotor", ln) and ("router" in rel or "api" in rel):
            f.append(Finding(BLOCK, "MONGO-DUALWRITE", rel, i,
                "Direct Mongo write from a request handler — the note is lost if it fails.",
                "schema §4A.3: project via outbox_events in the same transaction"))

        # --- cross-module raw SQL ------------------------------------------------
        m = re.search(r"(?:FROM|JOIN|UPDATE|INSERT INTO)\s+([a-z_]{4,})", ln)
        if m and "/app/" in rel:
            table = m.group(1)
            module = rel.split("/app/")[1].split("/")[0]
            owned = {"patients": {"patients","patient_identifiers","patient_merge_log"},
                     "users": {"users","facilities","idempotency_keys"},
                     "billing": {"invoices","invoice_items","payments","refunds","billing_counters"},
                     "queue": {"queues","queue_tokens","queue_counters","queue_token_priority_changes","rosters"}}
            shared = {"audit_logs","data_access_log","outbox_events","notification_history","files"}
            if module in owned and table not in owned[module] and table not in shared:
                f.append(Finding(WARN, "MODULE-BOUNDARY", rel, i,
                    f"'{module}' queries '{table}' directly — cross-module reads go through service functions.",
                    "architecture §4 boundary rule"))

    # --- AST-level checks ------------------------------------------------------
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return f

    if is_migration:
        names = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        if "downgrade" not in names:
            f.append(Finding(BLOCK, "MIG-DOWNGRADE", rel, 1,
                "Migration has no downgrade().", "conventions §1.10"))
        else:
            for n in ast.walk(tree):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "downgrade":
                    if len(n.body) == 1 and isinstance(n.body[0], ast.Pass):
                        f.append(Finding(BLOCK, "MIG-DOWNGRADE", rel, n.lineno,
                            "downgrade() is empty (pass).", "conventions §1.10"))
        if not re.search(r'^revision\s*=\s*["\']\d{4}["\']', src, re.M):
            f.append(Finding(BLOCK, "MIG-REVISION", rel, 1,
                "revision must be a 4-digit zero-padded string (e.g. '0007').", "schema §2"))
        if re.search(r'^revision\s*=\s*["\']0018["\']', src, re.M):
            f.append(Finding(BLOCK, "MIG-0018", rel, 1,
                "Revision 0018 is retired and must never be created.", "schema §2"))

    # hand-rolled mixin columns in models
    if "models.py" in rel:
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {b.id for b in node.bases if isinstance(b, ast.Name)}
            if "Base" not in bases:
                continue
            assigned = {t.target.id for t in node.body
                        if isinstance(t, ast.AnnAssign) and isinstance(t.target, ast.Name)}
            hand = assigned & MIXIN_COLS
            if hand and not (bases & {"UUIDPk", "Timestamps", "Blame"}):
                f.append(Finding(BLOCK, "MIXIN", rel, node.lineno,
                    f"class {node.name} hand-rolls {sorted(hand)} instead of inheriting "
                    f"UUIDPk/Timestamps/Blame.", "conventions §1.9"))

    # POST create endpoints without idempotency
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decs = [ast.unparse(d) for d in node.decorator_list]
            if any(".post(" in d for d in decs):
                args = {a.arg for a in node.args.args} | {a.arg for a in node.args.kwonlyargs}
                if "idempotency_key" not in args and "Idempotency" not in src:
                    f.append(Finding(WARN, "IDEMPOTENCY", rel, node.lineno,
                        f"POST handler '{node.name}' has no Idempotency-Key handling — "
                        "a retry on a flaky link creates a duplicate.",
                        "schema §4A.1"))
    return f

def changed_files() -> list[pathlib.Path]:
    try:
        base = subprocess.run(["git","merge-base","HEAD","origin/staging"],
                              capture_output=True, text=True).stdout.strip() or "HEAD~1"
        out = subprocess.run(["git","diff","--name-only",base,"HEAD"],
                             capture_output=True, text=True).stdout.split()
    except Exception:
        out = []
    return [pathlib.Path(p) for p in out if p.endswith(".py") and pathlib.Path(p).exists()]

def main() -> int:
    args = sys.argv[1:]
    if args == ["--all"]:
        files = list(pathlib.Path("backend").rglob("*.py"))
    elif args:
        files = [pathlib.Path(a) for a in args]
    else:
        files = changed_files()
    files = [f for f in files if "__pycache__" not in str(f)]
    if not files:
        print("PR CHECK: no python files to check"); return 0
    findings = [x for f in files for x in check_file(f)]
    blockers = [x for x in findings if x.sev == BLOCK]
    warns = [x for x in findings if x.sev == WARN]
    print(f"PR CHECK — {len(files)} file(s), {len(blockers)} blocker(s), {len(warns)} warning(s)\n")
    for x in blockers: print(x)
    if blockers and warns: print()
    for x in warns: print(x)
    if not findings: print("  ✓ clean")
    return 1 if blockers else 0

if __name__ == "__main__":
    sys.exit(main())
