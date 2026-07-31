#!/usr/bin/env bash
# Triage every open PR into staging — what's waiting on you, and which reviewer to run.
#
#   ./scripts/pr-triage.sh              # list all open PRs targeting staging
#   ./scripts/pr-triage.sh --mine       # only ones awaiting YOUR review
#
# Prints, per PR: number, author, size, CI state, review state, and the exact
# review command to run next.
set -uo pipefail
cd "$(dirname "$0")/.."

FILTER="${1:-}"
REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null) || {
  echo "gh not authenticated — run: gh auth login"; exit 2; }

echo "=========================================================================="
echo " Open PRs → staging   ($REPO)"
echo "=========================================================================="

gh pr list --base staging --state open --limit 50 \
  --json number,title,author,additions,deletions,files,reviewDecision,statusCheckRollup,isDraft \
  --jq '.[] | @json' | while read -r pr; do

  N=$(echo "$pr"      | python3 -c 'import sys,json;print(json.load(sys.stdin)["number"])')
  TITLE=$(echo "$pr"  | python3 -c 'import sys,json;print(json.load(sys.stdin)["title"][:60])')
  AUTHOR=$(echo "$pr" | python3 -c 'import sys,json;print(json.load(sys.stdin)["author"]["login"])')
  SIZE=$(echo "$pr"   | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["additions"]+d["deletions"])')
  DRAFT=$(echo "$pr"  | python3 -c 'import sys,json;print(json.load(sys.stdin)["isDraft"])')
  DECISION=$(echo "$pr" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("reviewDecision") or "PENDING")')
  CI=$(echo "$pr" | python3 -c '
import sys,json
d=json.load(sys.stdin).get("statusCheckRollup") or []
states=[c.get("conclusion") or c.get("state") or "" for c in d]
if not states: print("no-ci")
elif any(s in ("FAILURE","ERROR") for s in states): print("FAILING")
elif any(s in ("PENDING","IN_PROGRESS","QUEUED","") for s in states): print("running")
else: print("green")')
  AREA=$(echo "$pr" | python3 -c '
import sys,json
fs=[f["path"] for f in json.load(sys.stdin)["files"]]
be=any(p.startswith(("backend/","infra/","docs/")) for p in fs)
fe=any(p.startswith("frontend/") for p in fs)
print("both" if be and fe else "frontend" if fe else "backend" if be else "other")')

  [ "$FILTER" = "--mine" ] && [ "$DECISION" != "PENDING" ] && continue

  case "$DECISION" in
    APPROVED)          MARK="✅ approved" ;;
    CHANGES_REQUESTED) MARK="🔴 changes requested" ;;
    *)                 MARK="⏳ awaiting review" ;;
  esac
  [ "$DRAFT" = "True" ] && MARK="📝 draft"

  case "$CI" in
    FAILING) CIM="❌ CI failing" ;;
    green)   CIM="✅ CI green" ;;
    running) CIM="⏳ CI running" ;;
    *)       CIM="— no CI" ;;
  esac

  SIZEM=""
  [ "$SIZE" -gt 400 ] && SIZEM="  ⚠️ ${SIZE} lines (>400)"

  printf "\n#%-4s %-60s\n" "$N" "$TITLE"
  printf "      @%-18s %-22s %-14s %s%s\n" "$AUTHOR" "$MARK" "$CIM" "$AREA" "$SIZEM"

  case "$AREA" in
    frontend) printf "      → ./scripts/review-frontend-pr.sh %s\n" "$N" ;;
    backend)  printf "      → ./scripts/review-backend-pr.sh %s\n" "$N" ;;
    both)     printf "      → ./scripts/review-backend-pr.sh %s  &&  ./scripts/review-frontend-pr.sh %s\n" "$N" "$N" ;;
    *)        printf "      → gh pr diff %s\n" "$N" ;;
  esac
done

echo
echo "=========================================================================="
echo " Review a PR:   ./scripts/review-backend-pr.sh <n>   (add --post to comment)"
echo " Request fixes: gh pr review <n> --request-changes --body-file <file>"
echo " Approve:       gh pr review <n> --approve --body '...'"
echo " Checklist:     docs/PR-REVIEW-CHECKLIST.md"
echo "=========================================================================="
