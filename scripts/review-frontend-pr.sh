#!/usr/bin/env bash
# Autonomous end-to-end review of a FRONTEND pull request.
#
#   ./scripts/review-frontend-pr.sh 262
#   ./scripts/review-frontend-pr.sh 262 --post
#
# Exit 0 = no blockers, 1 = blockers found.
# Requires: gh (authenticated), node, npm.
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
echo " HealthDoc — frontend PR review  #$PR"
echo "=============================================="

step "PR metadata"
gh pr view "$PR" --json title,author,additions,deletions,files \
  --jq '"  title:  \(.title)\n  author: \(.author.login)\n  size:   +\(.additions) −\(.deletions), \(.files|length) files"' \
  || { echo "cannot read PR $PR"; exit 2; }

SIZE=$(gh pr view "$PR" --json additions,deletions --jq '.additions + .deletions')
if [ "$SIZE" -gt 400 ]; then warn "PR is $SIZE lines (limit 400)"; else pass "size within limit ($SIZE)"; fi

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

BASE=$(git merge-base HEAD origin/staging)
CHANGED=$(git diff --name-only "$BASE" HEAD)
if ! echo "$CHANGED" | grep -q '^frontend/'; then
  warn "no frontend/ files changed — is this a backend PR? use review-backend-pr.sh"
fi
echo "$CHANGED" | sed 's/^/    /' | head -25

step "Install"
if (cd frontend && npm ci --silent 2>/dev/null || npm install --silent); then
  pass "dependencies installed"
else
  fail "npm install failed"
fi

step "Frontend convention check (fe_check.mjs)"
if (cd frontend && node "$TOOLDIR/fe_check.mjs" --all); then pass "no convention blockers"; else fail "convention blockers — see above"; fi

step "TypeScript"
if (cd frontend && npx --no-install tsc --noEmit 2>&1 | tail -20); then pass "typecheck clean"; else fail "TypeScript errors"; fi

step "Lint"
if (cd frontend && npm run lint --silent 2>&1 | tail -20); then pass "eslint clean"; else warn "eslint findings"; fi

step "Build"
if (cd frontend && npm run build --silent >/dev/null 2>&1); then pass "next build succeeded"; else fail "build failed"; fi

step "Tests"
if (cd frontend && npm run test --silent 2>&1 | tail -10); then
  pass "tests passed"
else
  warn "no test script or tests failing — frontend tests are still being introduced"
fi

step "API contract sanity"
# every api() path should start with a documented endpoint group
UNKNOWN=$(grep -rhoE 'api<[^>]*>\(\s*[`"'"'"']/[a-z0-9-]+' frontend/app frontend/lib frontend/components 2>/dev/null \
  | grep -oE '/[a-z0-9-]+$' | sort -u \
  | while read -r p; do grep -q "\`$p" docs/database-schema.md || echo "$p"; done)
if [ -n "$UNKNOWN" ]; then
  warn "api() paths not found in the schema doc §4.4: $(echo "$UNKNOWN" | tr '\n' ' ')"
else
  pass "all api() paths appear in the documented contract"
fi

step "Human judgement still required"
cat <<'EOT'
    1. Role guard: does the screen check the caller's role before rendering?
    2. Capability gate: optional-module screens must read /facility/capabilities
       and render "not offered" on 409 module_disabled — not an error page.
    3. Envelope: are errors surfaced from ApiError (code + message), never raw?
    4. Money: displayed via formatMoney(string) — never parseFloat.
    5. Dates: formatDateTime with the facility timezone, not the browser's.
    6. Idempotency: creating forms generate the key when the form OPENS, not on submit.
    7. Optimistic concurrency: PATCH sends If-Match and handles 409 stale_write with a diff.
    8. Accessibility + offline: what does this screen show when the edge server is unreachable?
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
    echo "## Automated frontend review"
    echo
    cat "$REPORT"
    echo
    if [ "$BLOCKERS" -eq 0 ]; then
      echo "**No automated blockers.** Proceeding to human review of the UX/contract items."
    else
      echo "**$BLOCKERS blocker(s) — requesting changes.** See \`docs/PR-REVIEW-CHECKLIST.md\`."
    fi
  } | gh pr comment "$PR" --body-file -
  echo "posted verdict to PR #$PR"
fi

exit $((BLOCKERS > 0))
