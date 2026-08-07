#!/usr/bin/env bash
# Produce ONE reviewable bundle for a PR — metadata + automated checks + the diff —
# sized to paste into a chat for a second opinion.
#
#   ./scripts/pr-bundle.sh 261                 # print to screen
#   ./scripts/pr-bundle.sh 261 > /tmp/pr261.txt && open /tmp/pr261.txt
#   ./scripts/pr-bundle.sh 261 | pbcopy        # straight to clipboard (macOS)
#
# Safe: checks out the PR, gathers everything, restores your branch.
set -uo pipefail
cd "$(dirname "$0")/.."

PR="${1:?Usage: $0 <pr-number>}"
MAX_DIFF_LINES="${MAX_DIFF_LINES:-1200}"

# ---- DIRTY CHECK: gh pr checkout refuses on a dirty tree -------------------
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "✗ Your working tree has uncommitted changes — gh pr checkout will refuse."
  echo
  git status --short | head -20
  echo
  echo "Fix with ONE of:"
  echo "  git stash push -u -m 'wip'      # set aside, restore later with: git stash pop"
  echo "  git add -A && git commit -m ...  # commit them"
  exit 2
fi

# Fetch BEFORE snapshotting the checkers. Snapshotting from a stale
# origin/staging ref, then merging the freshly-fetched staging into the PR,
# runs OLD checkers against a NEW tree — which is how #265 got 20 phantom
# "audit_logs column missing" blockers: the merge brought in the doc change
# from #317 while the snapshot still held the checker from before it.
git fetch -q --no-tags origin staging 2>/dev/null

# The checkers live on staging; a PR branch predates them. Snapshot them
# to a temp dir first so they still run after we check the PR out.
TOOLDIR=$(mktemp -d)
git show origin/staging:backend/scripts/pr_check.py               > "$TOOLDIR/pr_check.py" 2>/dev/null || true
git show origin/staging:backend/scripts/spec_check.py             > "$TOOLDIR/spec_check.py" 2>/dev/null || true
git show origin/staging:backend/scripts/check_migration_integrity.py > "$TOOLDIR/check_migration_integrity.py" 2>/dev/null || true
git show origin/staging:backend/scripts/schema_drift_check.py      > "$TOOLDIR/schema_drift_check.py" 2>/dev/null || true
git show origin/staging:frontend/scripts/fe_check.mjs             > "$TOOLDIR/fe_check.mjs" 2>/dev/null || true
git show origin/staging:docs/database-schema.md                   > "$TOOLDIR/database-schema.md" 2>/dev/null || true

ORIGINAL_BRANCH=$(git rev-parse --abbrev-ref HEAD)
cleanup() {
  git merge --abort 2>/dev/null || git reset -q --hard HEAD 2>/dev/null || true
  git checkout -q "$ORIGINAL_BRANCH" 2>/dev/null || true
}
trap cleanup EXIT

if ! gh pr checkout "$PR" -f 2>/tmp/ghco.err; then
  echo "✗ gh pr checkout $PR failed:"; sed 's/^/    /' /tmp/ghco.err; exit 2
fi
BASE=$(git merge-base HEAD origin/staging)

# ---- Run the checkers against base-merged-with-head, which is what CI tests ----
#
# Checking out the PR head alone means every branch opened before a recent staging
# change gets flagged for that change. After 0003a merged, ~12 open PRs would each
# have reported "facilities.timezone missing" — a defect none of them caused and
# none of them would see in CI. False alarms at that rate teach people to skip the
# output, which costs more than the check is worth.
#
# HEAD still points at the PR head commit during a --no-commit merge, so the diff
# below remains the PR's own changes; only the working tree the checkers read is
# merged.
MERGE_NOTE="merged with origin/staging (same as CI)"
if ! git merge --no-commit --no-ff -q origin/staging >/dev/null 2>&1; then
  CONFLICTED=$(git diff --name-only --diff-filter=U | tr '\n' ' ')
  git merge --abort 2>/dev/null || true
  MERGE_NOTE="⚠ CONFLICTS with staging — checks below ran on the PR head ALONE.
        Conflicting: ${CONFLICTED:-unknown}
        This PR cannot merge until the author rebases."
fi

echo "=========================================================="
echo "PR #$PR BUNDLE"
echo "=========================================================="
gh pr view "$PR" --json number,title,author,additions,deletions,baseRefName,headRefName,body \
  --jq '"title:  \(.title)
author: \(.author.login)
branch: \(.headRefName) → \(.baseRefName)
size:   +\(.additions) −\(.deletions)

description:
\(.body // "(none)")"'

echo
echo "---------- FILES CHANGED ----------"
git diff --stat "$BASE" HEAD

echo
echo "---------- AUTOMATED CHECKS ----------"
echo "state:  $MERGE_NOTE"
echo
echo "\$ pr_check.py (from staging)"
python3 "$TOOLDIR/pr_check.py" --all 2>&1 || true
echo
echo "\$ spec_check.py"
if grep -q "ModuleCode enum — EXACTLY" docs/database-schema.md 2>/dev/null; then
  python3 "$TOOLDIR/spec_check.py" . 2>&1 || true
else
  echo "SPEC CHECK: skipped — this branch predates the current schema doc."
  echo "  (branch doc version: $(grep -oE '^\| v[0-9.]+' docs/database-schema.md 2>/dev/null | tail -1 | tr -d '| ') ,"
  echo "   staging is $(grep -oE '^\| v[0-9.]+' "$TOOLDIR/database-schema.md" 2>/dev/null | head -1 | tr -d '| '))"
  echo "  → the author must rebase on staging before this check is meaningful."
fi
echo
echo "\$ check_migration_integrity.py"
(cd backend && python3 "$TOOLDIR/check_migration_integrity.py" 2>&1) || true
echo
echo "\$ schema_drift_check.py"
(cd backend && python3 "$TOOLDIR/schema_drift_check.py" 2>&1) || true
if git diff --name-only "$BASE" HEAD | grep -q '^frontend/'; then
  echo
  echo "\$ fe_check.mjs"
  (cd frontend && node scripts/fe_check.mjs 2>&1) || true
fi
echo
echo "\$ pytest"
(cd backend && python3 -m pytest -q 2>&1 | tail -15) || true

echo
echo "---------- MIGRATIONS IN THIS PR (full) ----------"
MIGS=$(git diff --name-only "$BASE" HEAD | grep 'backend/migrations/versions/.*\.py$' || true)
if [ -z "$MIGS" ]; then
  echo "(none)"
else
  for m in $MIGS; do
    echo "===== $m ====="
    cat "$m" 2>/dev/null || echo "(deleted)"
    echo
  done
fi

echo "---------- DIFF ----------"
DIFF_LINES=$(git diff "$BASE" HEAD -- . ':(exclude)*.lock' ':(exclude)package-lock.json' | wc -l | tr -d ' ')
if [ "$DIFF_LINES" -gt "$MAX_DIFF_LINES" ]; then
  echo "(diff is $DIFF_LINES lines — showing code files only; rerun with"
  echo " MAX_DIFF_LINES=99999 ./scripts/pr-bundle.sh $PR  for everything)"
  echo
  git diff "$BASE" HEAD -- '*.py' '*.ts' '*.tsx' '*.sql' '*.yml' '*.json' \
    ':(exclude)package-lock.json' | head -"$MAX_DIFF_LINES"
else
  git diff "$BASE" HEAD -- . ':(exclude)*.lock' ':(exclude)package-lock.json'
fi

echo
echo "=========================================================="
echo "END OF BUNDLE — PR #$PR"
echo "=========================================================="
