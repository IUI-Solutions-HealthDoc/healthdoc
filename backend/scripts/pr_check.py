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

def _prose_line_numbers(src: str) -> set[int]:
    """Lines that are ONLY commentary — comments and docstrings.

    Deliberately NOT "all string literals". Raw SQL lives in text(\"\"\"...\"\"\")
    blocks all over this codebase, and that SQL is executable code that must be
    checked. Skipping every string made pr_check blind to it — #270 had
    `SELECT COALESCE(MAX(version), 0) + 1` inside a text() block and SEQ-RACE
    stayed silent.

    So: skip comment-only lines, and skip docstrings (identified via the AST,
    not by "is a string"). Everything else is checked.
    """
    import ast
    import io
    import tokenize

    lines = src.splitlines()
    prose: set[int] = set()

    # 1. comment-only lines (a trailing comment does not excuse the code on it)
    try:
        residual = [list(ln) for ln in lines]
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type != tokenize.COMMENT:
                continue
            (r1, c1), (r2, c2) = tok.start, tok.end
            for row in range(r1, min(r2, len(residual)) + 1):
                chars = residual[row - 1]
                lo = c1 if row == r1 else 0
                hi = c2 if row == r2 else len(chars)
                for col in range(lo, min(hi, len(chars))):
                    chars[col] = " "
        prose |= {n for n, chars in enumerate(residual, 1) if not "".join(chars).strip()}
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return {n for n, ln in enumerate(lines, 1) if ln.strip().startswith("#")}

    # 2. docstrings only — module, class, function. Not arbitrary strings.
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return prose

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            prose |= set(range(first.lineno, (first.end_lineno or first.lineno) + 1))

    return prose


def _downgrade_line_numbers(src: str) -> set[int]:
    """Lines inside a migration's downgrade() body.

    A downgrade exists to restore the PREVIOUS schema state, so by definition it
    recreates things the current rules forbid. Reverting `facility_type` to
    varchar(30) is what a correct downgrade of a widening migration looks like —
    flagging it as an ENUM-WIDTH violation asks the author to write a downgrade
    that doesn't downgrade. (Found on PR #264, migration 0035.)

    Only shape rules ("the schema must look like X") skip these lines. Danger
    rules — SEQ-RACE, PII-AADHAAR, MONGO-DUALWRITE, TZ-DATE — still apply: a
    downgrade that leaks Aadhaar or races on a counter is wrong in either
    direction.
    """
    import ast

    try:
        tree = ast.parse(src)
    except SyntaxError:
        return set()

    for node in ast.walk(tree):
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "downgrade"):
            end = node.end_lineno or node.lineno
            return set(range(node.lineno, end + 1))
    return set()


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

    # --- unresolved merge conflict markers ------------------------------------
    # Checked before anything else and returned immediately: a file with conflict
    # markers is not valid Python, so every AST-based rule below silently skips it
    # and the file reports clean. That is exactly what happened on PR #284 —
    # pr_check said "0 blockers" on three files that could not even be imported.
    conflict_lines = [
        i for i, ln in enumerate(src.splitlines(), 1)
        if ln.startswith(("<<<<<<< ", "=======", ">>>>>>> ")) and ln.rstrip() != "======="
        or ln.rstrip() == "======="
        and any(o.startswith("<<<<<<< ") for o in src.splitlines())
    ]
    if conflict_lines:
        return [Finding(BLOCK, "MERGE-CONFLICT", str(path), conflict_lines[0],
                        f"Unresolved merge conflict markers on {len(conflict_lines)} line(s) "
                        f"— the file is not valid source and every other check skips it.",
                        "resolve the conflict, then re-run the checks")]
    f: list[Finding] = []
    rel = str(path)
    lines = src.splitlines()
    is_model = "models.py" in rel or "migrations/versions/" in rel.replace("\\", "/")
    is_migration = "migrations/versions/" in rel.replace("\\", "/")

    # Comment/docstring line numbers — rules that look for *code* patterns must
    # skip these, or a line like "never MAX(col)+1 — it races" in a docstring
    # explaining that the author did the right thing gets reported as the wrong
    # thing. (Found on PR #271: the SEQ-RACE rule fired on Priyanshu's docstring
    # documenting that he used a Postgres sequence precisely to avoid MAX+1.)
    prose_lines = _prose_line_numbers(src)

    # Shape rules skip downgrade() — see _downgrade_line_numbers. Danger rules don't.
    downgrade_lines = _downgrade_line_numbers(src) if is_migration else set()

    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        if "pr-check: ignore" in ln:
            continue

        # Comment/docstring-only lines describe the rules; they don't break them.
        # (#271 SEQ-RACE fired on "never MAX(col)+1"; #269 TZ-DATE fired on
        #  "No CHECK against CURRENT_DATE" — both authors documenting that they
        #  had done the right thing.)
        if i in prose_lines:
            continue

        # --- race conditions on identifier allocation -------------------------
        if (re.search(r"\bmax\s*\(", ln, re.I)
                and re.search(r"\+\s*1|\bfunc\.max\b", ln, re.I)):
            f.append(Finding(BLOCK, "SEQ-RACE", rel, i,
                "MAX(col)+1 allocation races under concurrency (duplicate UHID/token/receipt).",
                "conventions §2.2: use a counters row with SELECT … FOR UPDATE"))

        # --- timezone / business date ----------------------------------------
        if re.search(r"CURRENT_DATE|now\(\)::date|utcnow\(\)\.date\(\)|datetime\.now\(\)\.date\(\)", ln):
            f.append(Finding(BLOCK, "TZ-DATE", rel, i,
                "Business date computed in UTC/naive — 00:00–05:30 IST resolves to YESTERDAY.",
                "schema §3: (now() AT TIME ZONE facilities.timezone)::date"))

        # --- money as float ---------------------------------------------------
        if (i not in downgrade_lines
                and re.search(r"\b(Float|REAL|DOUBLE|float)\b", ln)
                and any(h in ln.lower() for h in MONEY_HINTS)):
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
        if is_model and i not in downgrade_lines and re.search(r"String\((\d{1,2})\)", ln):
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
        # 4 digits, optionally one lowercase letter for a correction revision inserted
        # after an already-merged one (schema v3.15: '0003a' fixes gaps in 0003/0002
        # and must land BEFORE 0004, so it cannot simply be appended at the end).
        if not re.search(r'^revision\s*=\s*["\']\d{4}[a-z]?["\']', src, re.M):
            f.append(Finding(BLOCK, "MIG-REVISION", rel, 1,
                "revision must be 4 zero-padded digits, optionally + one letter for a "
                "correction revision (e.g. '0007', '0003a').", "schema §2"))
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
            assigned |= {tgt.id for stmt in node.body
                         if isinstance(stmt, ast.Assign)
                         for tgt in stmt.targets if isinstance(tgt, ast.Name)}
            # NOTE: `assigned` must include plain `x = Column(...)` assignments,
            # not just annotated `x: Mapped[...] = mapped_column(...)`. #269 used
            # the old style throughout and silently bypassed this rule entirely.
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
