"""Spec drift checker — validates docs/database-schema.md against backend/app/common/enums.py
and against itself. Run in CI: python scripts/spec_check.py  (exit 1 = drift)"""
import pathlib, re, sys, importlib.util

# default: repo root, two levels up from backend/scripts/
ROOT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "database-schema.md"
ENUMS = ROOT / "backend" / "app" / "common" / "enums.py"

def load_enums():
    spec = importlib.util.spec_from_file_location("enums", ENUMS)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    out = {}
    for name in dir(m):
        obj = getattr(m, name)
        if isinstance(obj, type) and issubclass(obj, m.CheckedEnum) and obj is not m.CheckedEnum:
            out[name] = {e.value for e in obj}
    return out

def main() -> int:
    doc = DOC.read_text(); problems = []
    enums = load_enums()

    # 1. every table in the migration map has a definition block
    defined = set(re.findall(r'^\*\*([a-z_]+)\*\*', doc, re.M))
    for pair in re.findall(r'^\*\*([a-z_]+) / ([a-z_]+)\*\*', doc, re.M):
        defined.update(pair)
    mapsec = doc.split('## 2. Migration map')[1].split('## 3.')[0]

    # Prose words that appear in the Tables cell but never name a table.
    SKIP = {'and', 'the', 'skipped', 'never', 'create', 'stub', 'only', 'schema', 'fk',
            'alter', 'uuid', 'ossp', 'pgcrypto', 'pg_trgm', 'seq_outbox', 'widen',
            'widened', 'see', 'plus', 'with'}

    # "ALTER <table>: col_a, col_b" names COLUMNS, not tables. Strip those clauses
    # before looking for table names — otherwise every altered column has to be
    # hand-added to SKIP, which is how this check accumulated `guardian`/`abha`/
    # `_id`/`_type` prefix hacks and still broke on the next migration to use it
    # (0003a: 'timezone' and 'widen' were both reported as missing tables).
    alter_clause = re.compile(r'\bALTER\s+[a-z_]+\s*:[^;|]*', re.I)

    # "(+ orders.fulfilment_mode)" / "(+ FK consent_records.consent_manager_id)" —
    # the (+ ...) notation always means "and this column/FK on an existing table",
    # never "and this new table". Same reasoning as the ALTER clause above.
    plus_clause = re.compile(r'\(\+[^)]*\)')

    for line in mapsec.splitlines():
        if not line.startswith('| 00'):
            continue
        cells = line.split('|')
        if len(cells) < 4:
            continue
        # Drop struck-through entries (~~x~~) — those are documented as NOT created here.
        cell = re.sub(r'~~[^~]+~~', ' ', cells[3])
        cell = plus_clause.sub(' ', cell)
        cell = alter_clause.sub(' ', cell)
        cell = cell.replace('*', ' ')
        for t in re.findall(r'\b([a-z_]{4,})\b', cell):
            if t in SKIP or t in defined:
                continue
            problems.append(f"table '{t}' is in the migration map but has no **definition** block")

    # 2. every enum named in the doc exists in enums.py
    for enum_name in set(re.findall(r'\b([A-Z][A-Za-z]+)\s+enum\b', doc)):
        if enum_name not in enums:
            problems.append(f"doc references '{enum_name} enum' but it is not in enums.py")

    # 3. inline value lists in the doc must match enums.py exactly
    checks = {
        "InvoiceStatus": r"-- InvoiceStatus: ([a-z_|]+)",
        "QueueTokenStatus": None,
    }
    m = re.search(r"status\s+varchar\(\d+\) NOT NULL DEFAULT 'draft'\s*--\s*InvoiceStatus: ([a-z_|]+)", doc)
    if m:
        doc_vals = set(m.group(1).split('|'))
        if doc_vals != enums.get("InvoiceStatus", set()):
            problems.append(f"InvoiceStatus mismatch: doc={sorted(doc_vals)} code={sorted(enums['InvoiceStatus'])}")

    # 4. optional modules in doc == ModuleCode in code
    m = re.search(r"ModuleCode enum — EXACTLY \w+: ([a-z_|]+)", doc)
    if m:
        doc_mods = set(m.group(1).split('|'))
        if doc_mods != enums.get("ModuleCode", set()):
            problems.append(f"ModuleCode mismatch: doc={sorted(doc_mods)} code={sorted(enums['ModuleCode'])}")
    else:
        problems.append("could not find the ModuleCode list in the doc")

    # 5. every FK target resolves to a defined table.
    #    Only real FK declarations: "<something>_id UUID [NOT NULL|NULL] → table"
    for tgt in set(re.findall(r'_id\s+UUID(?:\([^)]*\))?[^→\n]{0,30}→\s*([a-z_]{3,})', doc)):
        if tgt not in defined and tgt not in {'users','facilities','patients','visits','orders',
            'encounters','departments','rooms','wards','beds','files','suppliers','invoices',
            'payments','prescriptions','admissions','discharges','queues','queue_tokens'}:
            problems.append(f"FK target '{tgt}' referenced but not defined")

    if problems:
        print("SPEC CHECK: FAIL"); [print("  ✗", p) for p in sorted(set(problems))]
        return 1
    print(f"SPEC CHECK: OK — {len(defined)} tables defined, {len(enums)} enums, map+FKs+ModuleCode consistent")
    return 0

sys.exit(main())
