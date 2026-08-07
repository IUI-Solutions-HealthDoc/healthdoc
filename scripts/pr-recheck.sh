#!/usr/bin/env bash
# What has moved on EVERY open PR since it was last looked at?
#
#   ./scripts/pr-recheck.sh              # every open PR into staging
#   ./scripts/pr-recheck.sh --changed    # only ones with new commits since review
#   ./scripts/pr-recheck.sh 261 265      # specific ones
#
# For each PR: whether it has been reviewed, and whether the author has pushed
# since. Re-bundling a PR nobody has touched wastes a review cycle, and GitHub
# doesn't surface "pushed since your review" across a list.
#
# No heredocs inside $( ) anywhere: macOS ships bash 3.2, which mis-parses that
# combination.
set -uo pipefail
cd "$(dirname "$0")/.."

command -v gh >/dev/null || { echo "gh not installed"; exit 2; }
gh auth status >/dev/null 2>&1 || { echo "gh not authenticated — run: gh auth login"; exit 2; }

ONLY_CHANGED=0
ARGS=""
for a in "$@"; do
  if [ "$a" = "--changed" ]; then ONLY_CHANGED=1; else ARGS="$ARGS $a"; fi
done

if [ -n "$(echo "$ARGS" | tr -d ' ')" ]; then
  PRS="$ARGS"
else
  PRS=$(gh pr list --base staging --state open --limit 60 --json number --jq '.[].number')
fi

if [ -z "$(echo "$PRS" | tr -d ' ')" ]; then
  echo "No open PRs into staging."
  exit 0
fi

echo "=========================================================================="
echo " Open PRs → staging — what has moved"
echo "=========================================================================="

READY=""; WAITING=""; NEW=""

for PR in $PRS; do
  JSON=$(gh pr view "$PR" --json number,title,author,reviews,commits,additions,deletions,isDraft,reviewDecision 2>/dev/null)
  [ -z "$JSON" ] && continue

  SUMMARY=$(printf '%s' "$JSON" | python3 -c '
import sys, json
d = json.load(sys.stdin)

commits = d.get("commits") or []
last_commit = commits[-1]["committedDate"] if commits else ""

# Any review at all, and specifically the last one that requested changes.
revs = d.get("reviews") or []
last_any = revs[-1]["submittedAt"] if revs else ""
changes = [r for r in revs if r.get("state") == "CHANGES_REQUESTED"]
last_changes = changes[-1]["submittedAt"] if changes else ""

baseline = last_changes or last_any
if not baseline:
    state = "NEVER"            # never reviewed at all
elif last_commit and last_commit > baseline:
    state = "UPDATED"          # author pushed after the review
else:
    state = "WAITING"          # reviewed, nothing new

print("\t".join([
    state,
    d["title"][:50],
    d["author"]["login"],
    str(d["additions"] + d["deletions"]),
    last_commit or "-",
    baseline or "-",
    str(len(commits)),
    (d.get("reviewDecision") or "PENDING"),
    "draft" if d.get("isDraft") else "",
]))
')
  [ -z "$SUMMARY" ] && continue

  STATE=$(printf '%s' "$SUMMARY"   | cut -f1)
  TITLE=$(printf '%s' "$SUMMARY"   | cut -f2)
  AUTHOR=$(printf '%s' "$SUMMARY"  | cut -f3)
  SIZE=$(printf '%s' "$SUMMARY"    | cut -f4)
  PUSHED=$(printf '%s' "$SUMMARY"  | cut -f5)
  BASELINE=$(printf '%s' "$SUMMARY" | cut -f6)
  NCOMMITS=$(printf '%s' "$SUMMARY" | cut -f7)
  DECISION=$(printf '%s' "$SUMMARY" | cut -f8)
  DRAFT=$(printf '%s' "$SUMMARY"   | cut -f9)

  [ "$ONLY_CHANGED" = "1" ] && [ "$STATE" != "UPDATED" ] && continue

  case "$STATE" in
    UPDATED)
      printf "\n\033[32m● #%-4s\033[0m %s %s\n" "$PR" "$TITLE" "$DRAFT"
      printf "      @%-18s \033[32mpushed since review\033[0m — %s lines, %s commits, %s\n" \
        "$AUTHOR" "$SIZE" "$NCOMMITS" "$DECISION"
      printf "      reviewed %s\n      pushed   %s\n" "$BASELINE" "$PUSHED"
      printf "      → ./scripts/pr-bundle.sh %s | pbcopy\n" "$PR"
      READY="$READY $PR" ;;
    NEVER)
      printf "\n\033[33m○ #%-4s\033[0m %s %s\n" "$PR" "$TITLE" "$DRAFT"
      printf "      @%-18s \033[33mnever reviewed\033[0m — %s lines, %s commits\n" \
        "$AUTHOR" "$SIZE" "$NCOMMITS"
      printf "      → ./scripts/pr-bundle.sh %s | pbcopy\n" "$PR"
      NEW="$NEW $PR" ;;
    *)
      printf "\n  #%-4s %s %s\n" "$PR" "$TITLE" "$DRAFT"
      printf "      @%-18s no new commits since review — still with the author (%s)\n" \
        "$AUTHOR" "$DECISION"
      WAITING="$WAITING $PR" ;;
  esac
done

echo
echo "=========================================================================="
printf " ● updated since review: %s\n" "$([ -n "$READY" ] && echo "$READY" || echo 'none')"
printf " ○ never reviewed:       %s\n" "$([ -n "$NEW" ] && echo "$NEW" || echo 'none')"
printf "   still with author:    %s\n" "$([ -n "$WAITING" ] && echo "$WAITING" || echo 'none')"
echo "=========================================================================="
echo
echo " Review the ● first — those are responses to feedback you already gave."
echo " A PR with no new commits has had no work done on it; that needs a"
echo " conversation, not another review pass."
