from __future__ import annotations
"""Migration chain integrity checker (B1-W5-01 — supports B2's THID-merge review).

Verifies the Alembic migration set before merge, catching the mistakes that break
parallel development:
  1. duplicate revision ids
  2. broken chain (a down_revision pointing at a missing revision)
  3. multiple heads (two migrations with the same down_revision -> fork)
  4. missing downgrade() body
  5. reuse of retired number 0018

Run:  python scripts/check_migration_integrity.py
Exit code 0 = clean, 1 = problems (wire into CI).
"""
import pathlib
import re
import sys

VER_DIR = pathlib.Path(__file__).resolve().parent.parent / "migrations" / "versions"


def main() -> int:
    revs: dict[str, str] = {}       # revision -> down_revision
    files: dict[str, str] = {}      # revision -> filename
    problems: list[str] = []

    for f in sorted(VER_DIR.glob("*.py")):
        if f.name == "__init__.py":
            continue
        text = f.read_text()
        rev = _grab(text, r"^revision\s*=\s*['\"]([^'\"]+)['\"]")
        down = _grab(text, r"^down_revision\s*=\s*['\"]([^'\"]+)['\"]")
        if rev is None:
            problems.append(f"{f.name}: no revision id")
            continue
        if rev in revs:
            problems.append(f"duplicate revision {rev} ({files[rev]} & {f.name})")
        if rev == "0018":
            problems.append(f"{f.name}: revision 0018 is retired — never create it")
        if "def downgrade" not in text or re.search(r"def downgrade\([^)]*\):\s*\n\s*pass", text):
            problems.append(f"{rev} ({f.name}): downgrade() missing or empty")
        revs[rev] = down
        files[rev] = f.name

    # chain + heads
    downs = [d for d in revs.values() if d]
    for rev, down in revs.items():
        if down and down not in revs:
            problems.append(f"{rev}: down_revision {down} not found (broken chain)")
    dupe_downs = {d for d in downs if downs.count(d) > 1}
    for d in dupe_downs:
        forks = [r for r, dn in revs.items() if dn == d]
        problems.append(f"fork: {forks} all branch off {d} (multiple heads)")

    if problems:
        print("MIGRATION INTEGRITY: FAIL")
        for p in problems:
            print(f"  ✗ {p}")
        return 1
    print(f"MIGRATION INTEGRITY: OK ({len(revs)} migrations, linear chain)")
    return 0


def _grab(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text, re.M)
    return m.group(1) if m else None


if __name__ == "__main__":
    sys.exit(main())
