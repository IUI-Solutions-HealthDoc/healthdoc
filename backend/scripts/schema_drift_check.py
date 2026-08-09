#!/usr/bin/env python3
"""Does the schema doc match the migrations that actually exist?

`spec_check.py` compares the doc against `enums.py`. Nothing compared it against the
migrations — which is how `facilities.timezone` was specified in §3 from v3.0, created
by no migration, and went unnoticed for weeks while every review demanded TZ-DATE fixes
that reference it. `idempotency_keys` was in the §2 map under 0002 and read by
`billing/service.py`, also created nowhere. Both were found by hand on PR #264.

## Scoping: why this isn't 900 false alarms

Most migrations aren't merged yet, so most of §3 legitimately has no migration. Blindly
diffing doc-vs-disk would report every unwritten table and be ignored within a day.

So the rule is: **a table is in scope only once the migration that creates it exists on
disk.** Until then the doc is a specification and silence is correct. From the moment
the CREATE TABLE lands, the doc becomes a claim about reality and gets checked.

Two findings, both real defects rather than style:

  MISSING-COLUMN  §3 lists a column; the table is created by a migration on disk;
                  no migration anywhere adds that column. Code written against the
                  doc will fail at runtime. (facilities.timezone)

  MISSING-TABLE   The §2 map says revision X creates table T; revision X exists on
                  disk; T is created by no migration. (idempotency_keys)

The reverse direction (migration has a column §3 doesn't mention) is reported as a
warning only — §3 deliberately omits mixin columns.

Exit 1 on any finding. Usage:  python3 scripts/schema_drift_check.py
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

# Supplied by the UUIDPk / Timestamps / Blame mixins and never spelled out in §3.
MIXIN_COLUMNS = {
    "id", "created_at", "updated_at", "created_by", "updated_by", "row_version",
    "deleted_at",
}

# Words that appear where a column name would be in the doc's prose-style blocks.
NOT_A_COLUMN = {
    "unique", "index", "check", "primary", "foreign", "constraint", "partition",
    "partitioned", "note", "notes", "where", "and", "the", "see", "one", "all",
    "same", "must", "never", "always", "row", "rows", "table", "no", "on", "if",
}


def _locate() -> tuple[pathlib.Path, pathlib.Path]:
    """Resolve doc + versions dir from CWD first, then relative to this file.

    pr-bundle.sh runs checkers inside a snapshot of the PR, where __file__ points at
    the checked-out copy but the tree under test is CWD. Resolving from __file__ only
    made check_migration_integrity.py silently report "no versions dir".
    """
    for base in (pathlib.Path.cwd(), pathlib.Path.cwd() / "backend",
                 pathlib.Path(__file__).resolve().parents[1],
                 pathlib.Path(__file__).resolve().parents[2]):
        versions = base / "migrations" / "versions"
        for doc in (base / "docs" / "database-schema.md",
                    base.parent / "docs" / "database-schema.md"):
            if versions.is_dir() and doc.is_file():
                return doc, versions
    print("SCHEMA DRIFT: skipped — could not locate docs/database-schema.md "
          "and migrations/versions from here.")
    raise SystemExit(0)


# ----------------------------------------------------------------------------
# The doc side
# ----------------------------------------------------------------------------

def parse_doc_tables(doc_text: str) -> dict[str, set[str]]:
    """{table: {column, ...}} from §3. Handles both block styles the doc uses."""
    sec = doc_text.split("## 3. Canonical table definitions")
    if len(sec) < 2:
        return {}
    sec3 = re.split(r"\n## 4\.", sec[1])[0]
    tables: dict[str, set[str]] = {}

    # Style A — **table_name** followed by a fenced column block, allowing a few
    # lines of prose in between.
    #
    # A strictly adjacent match missed `audit_logs`: it has a two-line
    # **Policy: …** note between the header and the fence, so the biggest table
    # in the schema reported zero documented columns and was silently never
    # checked. But "nearest bold header anywhere above" is far too loose — §3
    # also contains prose and example fences, and that version attributed
    # sentences to audit_logs as column names.
    #
    # So: scan forward from each header, at most PROSE_GAP lines, and stop at
    # the next header. A block that isn't reached that way isn't a column list.
    PROSE_GAP = 6
    lines = sec3.splitlines()
    header_re = re.compile(r"^\*\*([a-z][a-z0-9_]*)\*\*")
    for i, line in enumerate(lines):
        h = header_re.match(line)
        if not h:
            continue
        for j in range(i + 1, min(i + 1 + PROSE_GAP, len(lines))):
            if header_re.match(lines[j]):
                break                      # next table started; this one has no fence
            if lines[j].startswith("```"):
                body: list[str] = []
                for k in range(j + 1, len(lines)):
                    if lines[k].startswith("```"):
                        break
                    body.append(lines[k])
                tables.setdefault(h.group(1), set()).update(
                    _columns_from_block("\n".join(body)))
                break

    # Style B — inline: **table** — `col type · col type · ...`
    for name, body in re.findall(r"^\*\*([a-z_]+)\*\*[^\n]*?—\s*`([^`]+)`", sec3, re.M):
        tables.setdefault(name, set()).update(
            _column_token(part) for part in body.split("·")
        )

    return {t: {c for c in cols if c} for t, cols in tables.items()}


def _columns_from_block(body: str) -> set[str]:
    cols: set[str] = set()
    for raw in body.splitlines():
        line = raw.split("--")[0].strip()          # drop trailing comment
        if not line:
            continue
        if "·" in line:                             # a packed line inside a fence
            for part in line.split("·"):
                cols.add(_column_token(part))
            continue
        cols.add(_column_token(line))
    return {c for c in cols if c}


def _column_token(part: str) -> str:
    part = part.split("--")[0].strip().lstrip("`").strip()
    m = re.match(r"^([a-z][a-z0-9_]{2,})\b", part)
    if not m:
        return ""
    tok = m.group(1)
    return "" if tok in NOT_A_COLUMN else tok


# ----------------------------------------------------------------------------
# The migration side
# ----------------------------------------------------------------------------

def parse_migrations(versions: pathlib.Path) -> tuple[dict[str, set[str]], set[str]]:
    """Returns ({table: {column,...}} , {tables created by a CREATE TABLE})."""
    found: dict[str, set[str]] = {}
    created: set[str] = set()

    for path in sorted(versions.glob("[0-9]*.py")):
        src = path.read_text()
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            fn = node.func.attr
            args = node.args
            if not args or not isinstance(args[0], ast.Constant):
                continue
            table = args[0].value
            if not isinstance(table, str):
                continue

            if fn == "create_table":
                created.add(table)
                bucket = found.setdefault(table, set())
                for a in args[1:]:
                    col = _column_name(a)
                    if col:
                        bucket.add(col)
            elif fn in ("add_column", "alter_column"):
                bucket = found.setdefault(table, set())
                if fn == "alter_column" and len(args) > 1 and isinstance(args[1], ast.Constant):
                    bucket.add(args[1].value)
                else:
                    for a in args[1:]:
                        col = _column_name(a)
                        if col:
                            bucket.add(col)

        # Raw SQL: partitioning, triggers and ALTERs that autogenerate can't express.
        #
        # The column list has to be parsed too, not just the table name. Partitioned
        # tables (audit_logs, data_access_log) are raw SQL precisely because Alembic
        # can't emit PARTITION BY — so recording the table as "created" with zero
        # columns made every documented column of those tables look missing. On #266
        # that produced 12 false blockers against a migration that defines all 12.
        for m in re.finditer(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_]+)\s*\((.*?)\)\s*"
            r"(?:PARTITION\s+BY|;)", src, re.I | re.S):
            table, body = m.group(1), m.group(2)
            created.add(table)
            bucket = found.setdefault(table, set())
            # Strip -- comments BEFORE splitting on commas. A comment like
            # "-- Per-facility monotonic write order, gaplessly assigned by"
            # contains a comma, which otherwise splits mid-comment and made the
            # next real column ('chain_seq') invisible while inventing a column
            # called 'gaplessly'. Both audit_logs columns it hid are ones other
            # reviews depend on.
            body = re.sub(r"--[^\n]*", "", body)
            depth = 0
            current: list[str] = []
            parts: list[str] = []
            for ch in body:                      # split on top-level commas only —
                if ch == "(":                    # VARCHAR(50) and CHECK (x IN (…))
                    depth += 1                   # both contain commas of their own
                elif ch == ")":
                    depth -= 1
                if ch == "," and depth == 0:
                    parts.append("".join(current)); current = []
                else:
                    current.append(ch)
            parts.append("".join(current))
            for part in parts:
                line = part.strip().split("--")[0].strip()
                token = re.match(r"^([a-z][a-z0-9_]*)\b", line)
                if token and token.group(1).upper() not in (
                        "CONSTRAINT", "PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "LIKE"):
                    bucket.add(token.group(1))
        # Tables created by raw SQL with no inline column list still count as created.
        for m in re.finditer(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_]+)",
                             src, re.I):
            created.add(m.group(1))
            found.setdefault(m.group(1), set())
        for m in re.finditer(r"ALTER\s+TABLE\s+([a-z_]+)\s+ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_]+)",
                             src, re.I):
            found.setdefault(m.group(1), set()).add(m.group(2))

    return found, created


def _column_name(node: ast.AST) -> str | None:
    """sa.Column("name", ...) -> "name"."""
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "Column" and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)):
        return node.args[0].value
    return None


def parse_doc_column_origins(doc_text: str) -> dict[tuple[str, str], str]:
    """{(table, column): revision} for columns §3 says a later migration adds.

    §3 already records this in the trailing comment — "added by 0030",
    "FK added in 0019", "added in 0022". Reading it means a branch that creates
    a table isn't blamed for columns a downstream migration owns.
    """
    sec = doc_text.split("## 3. Canonical table definitions")
    if len(sec) < 2:
        return {}
    sec3 = re.split(r"\n## 4\.", sec[1])[0]

    out: dict[tuple[str, str], str] = {}
    current: str | None = None
    header_re = re.compile(r"^\*\*([a-z][a-z0-9_]*)\*\*")
    # "added by 0030" / "added in 0022" / "FK added in 0019" — but NOT
    # "FK constraint added in 0005", which is about a constraint, not the column.
    added_re = re.compile(r"\badded\s+(?:by|in)\s+(\d{4}[a-z]?)\b", re.I)

    for line in sec3.splitlines():
        h = header_re.match(line)
        if h:
            current = h.group(1)
            continue
        if current is None or "--" not in line:
            continue
        col = _column_token(line)
        m = added_re.search(line.split("--", 1)[1])
        if col and m:
            out[(current, col)] = m.group(1)
    return out


def parse_map(doc_text: str) -> dict[str, set[str]]:
    """{revision: {table, ...}} from the §2 migration map."""
    if "## 2. Migration map" not in doc_text:
        return {}
    mapsec = doc_text.split("## 2. Migration map")[1].split("## 3.")[0]
    out: dict[str, set[str]] = {}
    for line in mapsec.splitlines():
        if not line.startswith("| 00"):
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 5:
            continue
        rev, tables_cell = cells[1], cells[3]
        tables_cell = re.sub(r"~~[^~]+~~", " ", tables_cell)     # struck through = not here
        tables_cell = re.sub(r"\(\+[^)]*\)", " ", tables_cell)   # (+ col) = a column
        tables_cell = re.sub(r"\bALTER\s+[a-z_]+\s*:[^;|]*", " ", tables_cell, flags=re.I)
        tables_cell = tables_cell.replace("*", " ")
        names = {t for t in re.findall(r"\b([a-z_]{4,})\b", tables_cell)
                 if t not in NOT_A_COLUMN}
        if names:
            out[rev] = names
    return out


# ----------------------------------------------------------------------------

def load_baseline() -> set[str]:
    """Accepted, already-existing drift — see schema_drift_baseline.txt.

    Deliberately a file rather than `|| true` in CI. A blanket suppression hides the
    next defect as well as this one; a baseline only ever hides the specific findings
    someone wrote down, so drift can shrink but not grow.
    """
    path = pathlib.Path(__file__).with_name("schema_drift_baseline.txt")
    if not path.is_file():
        return set()
    out = set()
    for line in path.read_text().splitlines():
        line = line.split("#")[0].strip()
        if line:
            out.add(re.sub(r"\s+", " ", line))
    return out


def _key(finding: str) -> str:
    """'[MISSING-COLUMN] §3 documents facilities.timezone, and ...' -> the stable bit."""
    m = re.match(r"\[(MISSING-COLUMN)\] §3 documents ([a-z_]+\.[a-z_]+)", finding)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    m = re.match(r"\[(MISSING-TABLE)\] §2 says (\S+) creates '([a-z_]+)'", finding)
    if m:
        return f"{m.group(1)} {m.group(2)} {m.group(3)}"
    return finding


def main() -> int:
    doc_path, versions = _locate()
    doc_text = doc_path.read_text()

    doc_tables = parse_doc_tables(doc_text)
    mig_tables, created = parse_migrations(versions)
    rev_map = parse_map(doc_text)
    on_disk = {p.name.split("_")[0] for p in versions.glob("[0-9]*.py")}

    blockers: list[str] = []
    warnings: list[str] = []

    # 1. MISSING-TABLE — the revision exists but doesn't create what the map promises.
    for rev, tables in sorted(rev_map.items()):
        if rev not in on_disk:
            continue
        for t in sorted(tables):
            if t not in created and t in doc_tables:
                blockers.append(
                    f"[MISSING-TABLE] §2 says {rev} creates '{t}', and {rev} is on disk, "
                    f"but no migration creates it.")

    # 2. MISSING-COLUMN — table exists in a migration, doc column created nowhere.
    #
    # A column added by a LATER migration than the CREATE TABLE is not missing,
    # it's just not merged yet. §3 says which revision adds it ("added by 0030",
    # "FK added in 0019"), so honour that: if the named revision isn't on disk,
    # the column isn't expected to be either. Without this, every branch that
    # creates `patients` reports the three ABHA columns from 0030 as missing.
    origins = parse_doc_column_origins(doc_text)
    for table, doc_cols in sorted(doc_tables.items()):
        if table not in created:
            continue                      # not built yet; doc is still a spec
        have = mig_tables.get(table, set())
        for col in sorted(doc_cols - have - MIXIN_COLUMNS):
            added_by = origins.get((table, col))
            if added_by and added_by not in on_disk:
                continue                  # a later migration owns it, and it isn't here
            blockers.append(
                f"[MISSING-COLUMN] §3 documents {table}.{col}, and {table} is created by "
                f"a migration, but no migration adds that column.")

    # 3. UNDOCUMENTED — migration has it, §3 doesn't. Warning: §3 omits mixins by design.
    for table, cols in sorted(mig_tables.items()):
        if table not in doc_tables:
            continue
        for col in sorted(cols - doc_tables[table] - MIXIN_COLUMNS):
            warnings.append(f"[UNDOCUMENTED] {table}.{col} exists in a migration "
                            f"but is not in §3.")

    # Split off drift that is already written down and owned.
    baseline = load_baseline()
    seen_keys = {_key(b) for b in blockers}
    accepted = [b for b in blockers if _key(b) in baseline]
    blockers = [b for b in blockers if _key(b) not in baseline]
    stale = sorted(baseline - seen_keys)

    scope = len(created & doc_tables.keys())
    print(f"SCHEMA DRIFT — {scope} table(s) in scope "
          f"({len(doc_tables)} documented, {len(created)} created on disk), "
          f"{len(blockers)} blocker(s), {len(warnings)} warning(s), "
          f"{len(accepted)} baselined")
    if not blockers and not warnings and not accepted:
        print("  OK — every documented column of every built table exists in a migration.")
    for b in blockers:
        print(f"  ✗ {b}")
    for w in warnings:
        print(f"  ! {w}")
    for a in accepted:
        print(f"  · {a}\n      (baselined — see scripts/schema_drift_baseline.txt)")
    for s in stale:
        print(f"  ! stale baseline entry '{s}' — this drift is fixed; delete the line.")
    if blockers:
        print("\n  A column in the doc that no migration creates is worse than an "
              "undocumented one:\n  code written against the spec fails at runtime, "
              "and reviews demand fixes that\n  reference it. Add the migration, or "
              "correct the doc.\n  If this drift predates your change, add it to "
              "schema_drift_baseline.txt with an owner.")
    return 1 if blockers else 0


if __name__ == "__main__":
    sys.exit(main())
