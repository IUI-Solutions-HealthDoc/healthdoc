#!/usr/bin/env bash
# Would staging's migration chain still resolve if this PR merged RIGHT NOW?
#
#   ./scripts/can-merge.sh 265
#
# Run this before every merge that touches backend/migrations/versions/.
#
# WHY THIS EXISTS
# Alembic builds the entire revision map before executing anything, so a single
# migration whose down_revision isn't present breaks EVERY command — including
# `upgrade 0003` on a database that never heard of the new revision. The error
# names a file the reader has never touched, so it reads as "my machine is
# broken" rather than "someone merged too early".
#
# That has now happened three times in one day:
#   #297  0032 -> 0031     parked
#   #327  0019 -> 0017     parked
#   #329  0009 -> 0008     parked   (PR carried THREE migrations; one resolved,
#                                    two didn't, and the one that resolved is
#                                    what got looked at)
#
# The existing checks don't catch this at merge time on purpose: a PR whose
# migration names an unmerged predecessor is the normal working state, and
# failing those would fail nearly every migration PR. check_migration_integrity
# is strict only on staging — which is accurate, but only tells you AFTER the
# outage. This is the missing question, asked before rather than after.
#
# Touches nothing: reads both refs with `git show`, no checkout, no worktree.
set -uo pipefail
cd "$(dirname "$0")/.."

PR="${1:?Usage: $0 <pr-number>}"

command -v gh >/dev/null || { echo "gh not installed"; exit 2; }

git fetch -q --no-tags origin staging || true
git fetch -q origin "refs/pull/${PR}/head:refs/remotes/pr/${PR}" 2>/dev/null || {
  echo "✗ could not fetch PR #${PR}"; exit 2; }

VERSIONS="backend/migrations/versions"

# The post-merge set is the union of what's on staging and what the PR adds.
# Anything in migrations/pending/ is deliberately parked and stays out of the
# CHAIN — but its revision ids are still TAKEN, checked separately below.
# Excluding pending/ entirely is how three PRs in one day picked a revision id
# a parked migration already owned: the author greps versions/, sees the
# number free, and nothing tells them otherwise.
{
  git ls-tree -r --name-only origin/staging -- "$VERSIONS" 2>/dev/null
  git ls-tree -r --name-only "pr/${PR}"     -- "$VERSIONS" 2>/dev/null
} | grep -E '/[0-9]{4}[a-z]?_.*\.py$' | sort -u > /tmp/canmerge_files.txt

# Revision ids owned by parked migrations.
git ls-tree -r --name-only origin/staging -- backend/migrations/pending 2>/dev/null \
  | grep -E '/[0-9]{4}[a-z]?_.*\.py$' > /tmp/canmerge_parked.txt || true

if [ ! -s /tmp/canmerge_files.txt ]; then
  echo "MERGE CHECK: no migrations involved — nothing to verify."
  exit 0
fi

python3 - "$PR" <<'PY'
import re
import subprocess
import sys

pr = sys.argv[1]
paths = [l.strip() for l in open("/tmp/canmerge_files.txt") if l.strip()]

def read(path):
    """Prefer the PR's copy — if it changed a migration, that's what merges."""
    for ref in (f"pr/{pr}", "origin/staging"):
        r = subprocess.run(["git", "show", f"{ref}:{path}"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout, ref
    return None, None

# Which FILES staging already has — not which ref happened to answer the read.
# Reading prefers the PR ref (its copy is what merges), so deriving "added by
# this PR" from the read source made every file look new.
staging_files = set(subprocess.run(
    ["git", "ls-tree", "-r", "--name-only", "origin/staging",
     "--", "backend/migrations/versions"],
    capture_output=True, text=True).stdout.split())

parked = {}
for pp in open("/tmp/canmerge_parked.txt").read().split():
    r = subprocess.run(["git", "show", f"origin/staging:{pp}"],
                       capture_output=True, text=True)
    if r.returncode == 0:
        m = re.search(r'^revision\s*=\s*["\']([^"\']+)', r.stdout, re.M)
        if m:
            parked[m.group(1)] = pp.rsplit("/", 1)[-1]

revs, downs, added = {}, {}, []
for p in paths:
    src, _ref = read(p)
    if src is None:
        continue
    m = re.search(r'^revision\s*=\s*["\']([^"\']+)', src, re.M)
    d = re.search(r'^down_revision\s*=\s*(?:["\']([^"\']+)|None)', src, re.M)
    if not m:
        continue
    rev = m.group(1)
    revs[rev] = p.rsplit("/", 1)[-1]
    downs[rev] = d.group(1) if d and d.group(1) else None
    if p not in staging_files:
        added.append(rev)

added = sorted(added)
dangling = {r: d for r, d in downs.items() if d and d not in revs}
collisions = {r: parked[r] for r in added if r in parked}

print("=" * 66)
print(f" Can PR #{pr} merge into staging right now?")
print("=" * 66)
print(f"\n  revisions after merge: {len(revs)}")
if added:
    print(f"  this PR adds:          {', '.join(added)}")

if collisions:
    print("\n  \033[31m✗ revision id already owned by a PARKED migration\033[0m\n")
    for rev in sorted(collisions):
        print(f"    {revs[rev]}  wants revision '{rev}'")
        print(f"      backend/migrations/pending/{collisions[rev]} already owns it")
    print("\n  Merges cleanly today; breaks the day that migration unparks. Two")
    print("  revisions with one id stops EVERY alembic command, for everyone.\n")
    print("  Pick a free id — `ls backend/migrations/pending/` is the list that")
    print("  grepping versions/ does not show you.")
    sys.exit(1)

if not dangling:
    print("\n  \033[32m✓ chain resolves — safe to merge\033[0m")
    sys.exit(0)

print("\n  \033[31m✗ chain would NOT resolve\033[0m\n")
for rev in sorted(dangling):
    where = "added by this PR" if rev in added else "already on staging"
    print(f"    {revs[rev]}  ({where})")
    print(f"      down_revision = '{dangling[rev]}' — not present after merge")
print("\n  Merging this leaves `alembic upgrade` broken for everyone, including")
print("  revisions unrelated to this PR.\n")
print("  Either merge the missing predecessor first, or move the affected")
print("  migration(s) to backend/migrations/pending/ and merge the rest.")
sys.exit(1)
PY
