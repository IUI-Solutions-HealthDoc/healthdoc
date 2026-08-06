#!/usr/bin/env bash
# Autonomous end-to-end review of a BACKEND pull request.
#
#   ./scripts/review-backend-pr.sh 261
#   ./scripts/review-backend-pr.sh 261 --post     # also post the verdict as a PR comment
#
# Runs every machine-checkable gate, prints a verdict, and leaves you only the
# judgement calls. Exit 0 = no blockers, 1 = blockers found.
#
# Requires: gh (authenticated), python3, docker (optional — for the live DB gate).
set -uo pipefail
cd "$(dirname "$0")/.."

PR="${1:?Usage: $0 <pr-number> [--post]}"
POST="${2:-}"
REPORT="$(mktemp)"
BLOCKERS=0
step() { printf "\n\033[1m── %s\033[0m\n" "$1"; }
fail() { BLOCKERS=$((BLOCKERS+1)); printf "  \033[31m✗ BLOCKER\033[0m %s\n" "$1"; echo "- ❌ **$1**" >> "$REPORT"; }
pass() { printf "  \033[32m✓\033[0m %s\n" "$1"; echo "- ✅ $1" >> "$REPORT"; }
warn() { printf "  \033[33m!\033[0m %s\n" "$1"; echo "- ⚠️ $1" >> "$REPORT"; }

echo "=============================================="
echo " HealthDoc — backend PR review  #$PR"
echo "=============================================="

# ── 0. metadata ───────────────────────────────────────────────────────────────
step "PR metadata"
gh pr view "$PR" --json title,author,additions,deletions,files \
  --jq '"  title:  \(.title)\n  author: \(.author.login)\n  size:   +\(.additions) −\(.deletions), \(.files|length) files"' \
  || { echo "cannot read PR $PR"; exit 2; }

SIZE=$(gh pr view "$PR" --json additions,deletions --jq '.additions + .deletions')
if [ "$SIZE" -gt 400 ]; then
  warn "PR is $SIZE lines (limit 400) — needs a stated reason in the description"
else
  pass "size within the 400-line limit ($SIZE)"
fi

# ── 1. check out ──────────────────────────────────────────────────────────────
step "Checking out"
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

# The checkers live on staging; a PR branch predates them. Snapshot them
# to a temp dir first so they still run after we check the PR out.
TOOLDIR=$(mktemp -d)
git show origin/staging:backend/scripts/pr_check.py               > "$TOOLDIR/pr_check.py" 2>/dev/null || true
git show origin/staging:backend/scripts/spec_check.py             > "$TOOLDIR/spec_check.py" 2>/dev/null || true
git show origin/staging:backend/scripts/check_migration_integrity.py > "$TOOLDIR/check_migration_integrity.py" 2>/dev/null || true
git show origin/staging:frontend/scripts/fe_check.mjs             > "$TOOLDIR/fe_check.mjs" 2>/dev/null || true
git show origin/staging:docs/database-schema.md                   > "$TOOLDIR/database-schema.md" 2>/dev/null || true

ORIGINAL_BRANCH=$(git rev-parse --abbrev-ref HEAD)
cleanup() { git checkout -q "$ORIGINAL_BRANCH" 2>/dev/null || true; }
trap cleanup EXIT
git fetch -q --no-tags origin staging
if ! gh pr checkout "$PR" -f 2>/tmp/ghco.err; then
  echo "✗ gh pr checkout $PR failed:"; sed 's/^/    /' /tmp/ghco.err; exit 2
fi
pass "checked out $(git rev-parse --abbrev-ref HEAD)"

# ── 2. does it even touch the backend? ────────────────────────────────────────
BASE=$(git merge-base HEAD origin/staging)
CHANGED=$(git diff --name-only "$BASE" HEAD)
if ! echo "$CHANGED" | grep -q '^backend/'; then
  warn "no backend/ files changed — is this a frontend PR? use review-frontend-pr.sh"
fi
echo "$CHANGED" | sed 's/^/    /' | head -25

# ── 3. convention checker (the 11 static rules) ───────────────────────────────
step "Convention check (pr_check.py)"
if python3 "$TOOLDIR/pr_check.py" --all; then pass "no convention blockers"; else fail "convention blockers — see above"; fi

# ── 4. spec drift: docs vs enums ──────────────────────────────────────────────
step "Spec drift (docs ↔ enums)"
if ! grep -q "ModuleCode enum — EXACTLY" docs/database-schema.md 2>/dev/null; then
  warn "branch predates the current schema doc — rebase on staging, then re-check"
elif python3 "$TOOLDIR/spec_check.py" .; then pass "schema doc and enums.py agree"
else fail "spec drift between docs and code"; fi

# ── 5. migration chain ────────────────────────────────────────────────────────
step "Migration integrity"
if (cd backend && python3 "$TOOLDIR/check_migration_integrity.py"); then
  pass "migration chain linear, downgrades present"
else
  fail "migration chain broken (dupes / fork / missing downgrade / retired 0018)"
fi

NEW_MIGRATIONS=$(echo "$CHANGED" | grep 'backend/migrations/versions/.*\.py' || true)
if [ -n "$NEW_MIGRATIONS" ]; then
  echo "  new migrations in this PR:"; echo "$NEW_MIGRATIONS" | sed 's/^/    /'
  warn "verify the migration NUMBER matches docs/database-schema.md §2 for this owner"
fi

# ── 6. lint + types ───────────────────────────────────────────────────────────
step "Lint"
if (cd backend && ruff check . 2>/dev/null); then pass "ruff clean"; else warn "ruff findings (see above)"; fi

# ── 7. tests ──────────────────────────────────────────────────────────────────
step "Tests"
if (cd backend && python3 -m pytest -q 2>&1 | tail -5); then pass "pytest passed"; else fail "tests failing"; fi

TESTS_ADDED=$(echo "$CHANGED" | grep -c 'backend/tests/' || true)
if [ "$TESTS_ADDED" -eq 0 ]; then
  warn "no test files touched — does this change really need no test?"
else
  pass "$TESTS_ADDED test file(s) touched"
fi

# ── 8. live database gate (optional, needs docker) ────────────────────────────
step "Live migration apply (optional)"
if command -v docker >/dev/null && docker compose -f infra/docker-compose.yml --env-file .env ps -q postgres 2>/dev/null | grep -q .; then
  if docker compose -f infra/docker-compose.yml --env-file .env exec -T backend alembic upgrade head >/dev/null 2>&1; then
    pass "alembic upgrade head succeeded against the running DB"
    if docker compose -f infra/docker-compose.yml --env-file .env exec -T backend \
         alembic downgrade -1 >/dev/null 2>&1 && \
       docker compose -f infra/docker-compose.yml --env-file .env exec -T backend \
         alembic upgrade head >/dev/null 2>&1; then
      pass "downgrade → upgrade round-trip works"
    else
      fail "downgrade is broken (cannot round-trip)"
    fi
  else
    fail "alembic upgrade head FAILED against the running DB"
  fi
else
  warn "stack not running — skipped the live migration gate (run 'make up' for full coverage)"
fi

# ── 9. verdict ────────────────────────────────────────────────────────────────
step "Human judgement still required"
cat <<'EOT'
    1. Migration number correct + merges in chain order?
    2. New tables match docs/database-schema.md §3 exactly (names, nullability, FKs, indexes)?
    3. New enum values added to BOTH enums.py and the doc?
    4. Every mutation writes audit_logs in the SAME transaction?
    5. Clinical reads: consent-gated and logged (including denials)?
    6. If this touches pharmacy/lab/radiology/ot/blood_bank — does the flow still work with it OFF?
    7. Mutable clinical/financial rows: row_version + If-Match honoured?
EOT

echo
echo "=============================================="
if [ "$BLOCKERS" -eq 0 ]; then
  printf " \033[32mVERDICT: no automated blockers\033[0m — proceed to human review\n"
else
  printf " \033[31mVERDICT: %s BLOCKER(S) — request changes\033[0m\n" "$BLOCKERS"
fi
echo "=============================================="

if [ "$POST" = "--post" ]; then
  {
    echo "## Automated backend review"
    echo
    cat "$REPORT"
    echo
    if [ "$BLOCKERS" -eq 0 ]; then
      echo "**No automated blockers.** Proceeding to human review of the spec/safety items."
    else
      echo "**$BLOCKERS blocker(s) — requesting changes.** See the checklist in \`docs/PR-REVIEW-CHECKLIST.md\`."
    fi
  } | gh pr comment "$PR" --body-file -
  echo "posted verdict to PR #$PR"
fi

exit $((BLOCKERS > 0))
