#!/usr/bin/env python3
"""Verify the Alembic migration chain is sane before anything is merged.

    python3 scripts/check_migration_integrity.py          # from backend/

Exit 1 on any problem. Checks:

  1. duplicate revision ids            — two devs both claim 0009
  2. broken chain                      — down_revision points at nothing
  3. forks                             — two migrations share a down_revision, so
                                         `alembic upgrade head` fails with "multiple heads"
  4. multiple heads                    — same thing, seen from the other end
  5. missing/stub downgrade            — you cannot roll back a bad deploy
  6. retired 0018                      — deliberately removed; must not come back
  7. map agreement                     — every migration on disk appears in
                                         docs/database-schema.md §2

NOTE: this file was referenced by pr-bundle.sh and the review scripts for weeks but did
not exist, so the gate silently passed on every PR reviewed so far. Missing tooling that
fails open is worse than no tooling — it produces a green tick nobody earned.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Branches where a dangling down_revision is an outage rather than a note.
_INTEGRATION_BRANCHES = {"staging", "main"}


def _on_integration_branch() -> bool:
    """True only when we ARE staging/main — not when we're a PR targeting it.

    The distinction matters. A PR whose migration names an unmerged predecessor
    is the normal working state: the §2 map assigns the number, and the PR ahead
    simply hasn't landed. Failing those would fail nearly every migration PR on
    the project and the check would be ignored within a day.

    What must never happen is that migration being MERGED while its predecessor
    is missing, because from that moment `alembic upgrade` is broken for
    everyone. So this is strict on a push to staging/main and quiet everywhere
    else — the PR reports it as a note for the reviewer to weigh, and staging
    goes red the instant it actually lands.
    """
    import os
    import subprocess

    if os.environ.get("GITHUB_EVENT_NAME") == "pull_request":
        return False  # a PR is allowed to be ahead of the chain
    ref = os.environ.get("GITHUB_REF_NAME")
    if ref:
        return ref in _INTEGRATION_BRANCHES
    try:
        out = subprocess.run(["git", "branch", "--show-current"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() in _INTEGRATION_BRANCHES
    except Exception:
        return False


def _locate() -> tuple[Path, Path]:
    """Find migrations/ and the schema doc.

    Resolve from the CWD first, not from __file__: pr-bundle.sh snapshots this
    script into a temp dir (so it can run against PR branches that predate it)
    and invokes it with `cd backend`. Anchoring on __file__ then points at
    /tmp/.../migrations and the check silently reports "no versions dir" —
    which is what it did on PRs #279 and #261.
    """
    for base in (Path.cwd(), Path.cwd().parent, Path(__file__).resolve().parents[1]):
        versions = base / "migrations" / "versions"
        if versions.is_dir():
            for docbase in (base, base.parent):
                doc = docbase / "docs" / "database-schema.md"
                if doc.exists():
                    return versions, doc
            return versions, base / "docs" / "database-schema.md"
    return Path.cwd() / "migrations" / "versions", Path.cwd() / "docs" / "database-schema.md"


VERSIONS, DOC = _locate()
RETIRED = {"0018"}


def parse() -> tuple[dict[str, dict], list[str]]:
    migrations: dict[str, dict] = {}
    problems: list[str] = []

    for path in sorted(VERSIONS.glob("[0-9]*.py")):
        src = path.read_text()
        # The character classes MUST exclude newlines. Without \n they span into the
        # function body and happily match the first quoted string they find there —
        # e.g. down_revision = None followed by op.drop_table("a") yields down = "a".
        rev_m = re.search(r'^revision\s*[:=]\s*[^"\'\n]*["\']([^"\']+)["\']', src, re.M)
        down_m = re.search(
            r'^down_revision\s*[:=]\s*[^"\'=\n]*(?:["\']([^"\']+)["\']|None)', src, re.M)
        if not rev_m:
            problems.append(f"{path.name}: no `revision = \"...\"` found")
            continue

        rev = rev_m.group(1)
        down = down_m.group(1) if (down_m and down_m.group(1)) else None

        if rev in migrations:
            problems.append(
                f"duplicate revision '{rev}': {migrations[rev]['file']} and {path.name} "
                f"— two branches claimed the same number; one must be renumbered")
        if rev in RETIRED:
            problems.append(
                f"{path.name}: revision '{rev}' was retired and must not be reintroduced")

        body = src.split("def downgrade()")[-1] if "def downgrade()" in src else ""
        stub = (not body) or re.fullmatch(r'\s*(->\s*None)?\s*:?\s*(""".*?""")?\s*(pass)?\s*',
                                          body, re.S) is not None
        if stub:
            problems.append(
                f"{path.name}: downgrade() is missing or a stub — a bad deploy cannot "
                f"be rolled back")

        migrations[rev] = {"file": path.name, "down": down}

    return migrations, problems


def main() -> int:
    if not VERSIONS.is_dir():
        print(f"MIGRATION CHECK: no versions dir at {VERSIONS}")
        return 1

    migrations, problems = parse()
    if not migrations:
        print("MIGRATION CHECK: no migrations found")
        return 1

    known = set(migrations)

    # Migrations declared in the doc's §2 map but not yet merged. A down_revision
    # pointing at one of those is EXPECTED on a feature branch — it is not a defect,
    # and reporting it as one trains everyone to ignore this checker.
    mapped_revs: set[str] = set()
    if DOC.exists():
        mapped_revs = set(re.findall(r"^\|\s*(\d{4}[a-z]?)\s*\|", DOC.read_text(), re.M))
    pending: list[str] = []

    # broken links
    for rev, info in sorted(migrations.items()):
        down = info["down"]
        if down is None or down in known:
            continue
        if down in mapped_revs:
            pending.append(
                f"{info['file']}: waits on '{down}', which is in the §2 map but not "
                f"merged yet")
        else:
            problems.append(
                f"{info['file']}: down_revision '{down}' is not a real revision and is "
                f"not in the §2 map — wrong number, or a typo")

    # forks: two migrations with the same parent
    parents: dict[str, list[str]] = {}
    for rev, info in migrations.items():
        if info["down"]:
            parents.setdefault(info["down"], []).append(rev)
    for parent, children in sorted(parents.items()):
        if len(children) > 1:
            problems.append(
                f"fork at '{parent}': {sorted(children)} all follow it — "
                f"`alembic upgrade head` will fail with multiple heads")

    # heads
    referenced = {i["down"] for i in migrations.values() if i["down"]}
    heads = sorted(known - referenced)
    if len(heads) > 1:
        # Several heads caused purely by unmerged gaps are expected mid-flight;
        # several heads with no gap between them is a real fork.
        if pending:
            pending.append(
                f"heads {heads} — expected while intermediate migrations are unmerged")
        else:
            problems.append(f"multiple heads: {heads} — the chain must be linear")

    roots = sorted(r for r, i in migrations.items() if i["down"] is None)
    if len(roots) > 1:
        problems.append(f"multiple roots: {roots} — only 0001 may have down_revision = None")

    # doc agreement
    if DOC.exists():
        doc = DOC.read_text()
        mapped = set(re.findall(r"^\|\s*(\d{4}[a-z]?)\s*\|", doc, re.M))
        for rev in sorted(known - mapped):
            problems.append(
                f"revision '{rev}' exists on disk but is not in the §2 migration map")

    # A dangling down_revision means something different depending on WHERE we are.
    #
    # On a feature branch it's expected and harmless: your migration names the
    # predecessor the §2 map assigns it, and that PR simply hasn't merged yet.
    # CI failing every such branch would be useless.
    #
    # On staging it is an outage. Alembic resolves the entire revision map before
    # executing anything, so one unreachable down_revision breaks `upgrade 0003`
    # for everyone, with an error naming a file the reader has never touched.
    # That has now happened twice — #297 (0032→0031) and #327 (0019→0017).
    #
    # So: same condition, different severity, decided by the branch we're on.
    if pending and _on_integration_branch():
        problems.extend(
            f"{p} — this is staging: an unresolvable down_revision breaks EVERY "
            f"alembic command here, not just this migration"
            for p in pending
        )
        pending = []

    if problems:
        print(f"MIGRATION CHECK: FAIL — {len(problems)} problem(s)\n")
        for p in problems:
            print(f"  ✗ {p}")
        for p in pending:
            print(f"  · {p}")
        if _on_integration_branch():
            print("\n  A migration whose predecessor isn't merged must not land on "
                  "staging.\n  Park it in migrations/pending/ until the chain reaches it "
                  "— see that\n  directory's README.")
        return 1

    if pending:
        print(f"MIGRATION CHECK: OK — {len(migrations)} migration(s), no defects. "
              f"{len(pending)} pending dependency note(s):")
        for p in pending:
            print(f"  · {p}")
        return 0

    chain = []
    cursor = roots[0] if roots else None
    seen = set()
    while cursor and cursor not in seen:
        seen.add(cursor)
        chain.append(cursor)
        cursor = next((r for r, i in migrations.items() if i["down"] == cursor), None)

    print(f"MIGRATION CHECK: OK — {len(migrations)} migration(s), linear, "
          f"downgrades present, head = {heads[0] if heads else '?'}")
    if len(chain) < len(migrations):
        print(f"  note: {len(migrations) - len(chain)} migration(s) not reachable from "
              f"the root — expected while intermediate migrations are unmerged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
