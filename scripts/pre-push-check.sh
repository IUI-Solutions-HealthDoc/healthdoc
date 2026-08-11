#!/usr/bin/env bash
# Run the four checks CI runs, before you push. Takes a few seconds.
#
#   ./scripts/pre-push-check.sh
#
# The point is that a reviewer should never be the first to tell you something
# a script could have. If this is clean, the automated half of the review is
# already done.
set -uo pipefail
cd "$(dirname "$0")/.."

FAILED=0
run() {
  local name="$1"; shift
  printf "\n\033[1m%s\033[0m\n" "$name"
  if "$@"; then
    printf "  \033[32m✓\033[0m\n"
  else
    printf "  \033[31m✗ — fix this before pushing\033[0m\n"
    FAILED=1
  fi
}

echo "=========================================================="
echo " Pre-push checks"
echo "=========================================================="

run "Schema doc vs enums.py" \
  bash -c 'cd backend && python3 scripts/spec_check.py ..'

run "Migration chain" \
  bash -c 'cd backend && python3 scripts/check_migration_integrity.py'

run "Schema doc vs migrations" \
  bash -c 'cd backend && python3 scripts/schema_drift_check.py'

run "Conventions (pr_check)" \
  bash -c 'cd backend && python3 scripts/pr_check.py'

# Tests: some need a live Postgres. If it isn't up, say so plainly and run the
# rest — reporting "✗ fix this" for a database you haven't started is a false
# alarm, and false alarms are how a check stops being read.
if ! (cd backend && python3 -c "import pytest" 2>/dev/null); then
  printf "\n\033[1mTests\033[0m\n  skipped — pytest not installed"
  printf " (pip install pytest pytest-asyncio)\n"
elif python3 - <<'PY' 2>/dev/null
import os, socket, urllib.parse
url = os.environ.get("TEST_DATABASE_URL") or os.environ.get(
    "DATABASE_URL", "postgresql://healthdoc@localhost:55432/healthdoc")
p = urllib.parse.urlparse(url.replace("+asyncpg", "").replace("+psycopg", ""))
s = socket.socket(); s.settimeout(1.5)
s.connect((p.hostname or "localhost", p.port or 5432))
s.close()
PY
then
  run "Tests" bash -c 'cd backend && python3 -m pytest -q'
else
  printf "\n\033[1mTests\033[0m\n"
  printf "  \033[33mPostgres not reachable — running non-DB tests only.\033[0m\n"
  printf "  Start the stack with 'make up' to run the full suite;\n"
  printf "  CI always runs all of it, so DB-backed failures will still surface there.\n"
  run "Tests (non-DB)" bash -c 'cd backend && python3 -m pytest -q --ignore=tests/audit'
fi

echo
echo "=========================================================="
if [ "$FAILED" -eq 0 ]; then
  echo " All clean. Push away."
else
  echo " Something failed above. CI will report the same thing —"
  echo " cheaper to fix it now than after a review round."
  echo
  echo " If you think a check is WRONG, say so in the PR. Several"
  echo " were wrong this week and got fixed. Don't work around it"
  echo " silently — that costs more than being mistaken."
fi
echo "=========================================================="
exit "$FAILED"
