#!/usr/bin/env bash
# Which PRs with requested changes have actually been updated since the review?
#
#   ./scripts/pr-recheck.sh              # every PR you've requested changes on
#   ./scripts/pr-recheck.sh 261 265 266  # specific ones
#
# Re-bundling a PR the author hasn't touched wastes a review cycle, and GitHub
# doesn't surface "pushed since your review" across a list. This compares the
# last commit timestamp against the last CHANGES_REQUESTED review timestamp.
#
# No heredocs inside $( ) anywhere in here: macOS ships bash 3.2, which
# mis-parses that combination (it already broke .issues/create-v3.14-issues.sh).
set -uo pipefail
cd "$(dirname "$0")/.."

command -v gh >/dev/null || { echo "gh not installed"; exit 2; }
gh auth status >/dev/null 2>&1 || { echo "gh not authenticated — run: gh auth login"; exit 2; }

if [ $# -gt 0 ]; then
  PRS="$*"
else
  PRS=$(gh pr list --base staging --state open --limit 50 \
        --json number,reviewDecision \
        --jq '.[] | select(.reviewDecision=="CHANGES_REQUESTED") | .number')
fi

if [ -z "$PRS" ]; then
  echo "No PRs are currently in the changes-requested state."
  exit 0
fi

echo "=========================================================================="
echo " Re-check — PRs with requested changes"
echo "=========================================================================="

READY=""
WAITING=""

for PR in $PRS; do
  JSON=$(gh pr view "$PR" --json number,title,author,reviews,commits,additions,deletions 2>/dev/null)
  [ -z "$JSON" ] && continue

  SUMMARY=$(printf '%s' "$JSON" | python3 -c '
import sys, json
d = json.load(sys.stdin)

commits = d.get("commits") or []
last_commit = commits[-1]["committedDate"] if commits else ""

# Only reviews that actually requested changes — a later COMMENT review
# would otherwise make everything look freshly reviewed.
changes = [r for r in (d.get("reviews") or []) if r.get("state") == "CHANGES_REQUESTED"]
last_review = changes[-1]["submittedAt"] if changes else ""

# New commits AFTER the review = author has responded. ISO-8601 UTC strings
# from the GitHub API sort correctly as plain strings.
updated = bool(last_commit and last_review and last_commit > last_review)

# Tab-separated so titles with spaces survive.
print("\t".join([
    "UPDATED" if updated else "WAITING",
    d["title"][:52],
    d["author"]["login"],
    str(d["additions"] + d["deletions"]),
    last_commit or "-",
    last_review or "-",
    str(len(commits)),
]))
')
  [ -z "$SUMMARY" ] && continue

  STATE=$(printf '%s' "$SUMMARY" | cut -f1)
  TITLE=$(printf '%s' "$SUMMARY" | cut -f2)
  AUTHOR=$(printf '%s' "$SUMMARY" | cut -f3)
  SIZE=$(printf '%s' "$SUMMARY" | cut -f4)
  PUSHED=$(printf '%s' "$SUMMARY" | cut -f5)
  REVIEWED=$(printf '%s' "$SUMMARY" | cut -f6)
  NCOMMITS=$(printf '%s' "$SUMMARY" | cut -f7)

  if [ "$STATE" = "UPDATED" ]; then
    printf "\n\033[32m● #%-4s\033[0m %s\n" "$PR" "$TITLE"
    printf "      @%-18s \033[32mpushed since your review\033[0m — %s lines, %s commits\n" \
      "$AUTHOR" "$SIZE" "$NCOMMITS"
    printf "      reviewed %s\n      pushed   %s\n" "$REVIEWED" "$PUSHED"
    printf "      → ./scripts/pr-bundle.sh %s | pbcopy\n" "$PR"
    READY="$READY $PR"
  else
    printf "\n  #%-4s %s\n" "$PR" "$TITLE"
    printf "      @%-18s no new commits since review — still with the author\n" "$AUTHOR"
    WAITING="$WAITING $PR"
  fi
done

echo
echo "=========================================================================="
if [ -n "$READY" ]; then
  printf " Ready to re-review:%s\n" "$READY"
else
  printf " Ready to re-review: none\n"
fi
if [ -n "$WAITING" ]; then
  printf " Still with author: %s\n" "$WAITING"
else
  printf " Still with author: none\n"
fi
echo "=========================================================================="
echo
echo " Only re-review the updated ones. A PR with no new commits has had no work"
echo " done on it — that needs a conversation, not another review pass."
