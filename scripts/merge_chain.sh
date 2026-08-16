#!/usr/bin/env bash
# Merge the migration chain in dependency order, stopping at the first failure.
#
#   #358  0023 vitals_nursing + 0024 procurement
#   #313  0025 hr_kpi
#   #360  0026 fhir_notifications      (retarget to staging first — stacked on #313)
#   #304  0027 facility_modules
#   #306  0028 user_account_requests
#   #307  0029 abac_policies
#   #308  0030 abha_linking_token
#   #309  0031 outbox
#
# Then 0032/0033/0034 unpark — they already chain off 0031 and need no edits.
#
# Each PR is BEHIND until the one before it lands, so update-branch runs first
# and CI is re-run against the new base. Stops on the first red so a broken
# migration never gets a later one stacked on top of it.
#
# Safe to re-run: anything already merged is skipped.
set -uo pipefail

# 0026 was #360, auto-closed when #313's branch was deleted on merge; the same
# commit is now #363 against staging.
CHAIN=(358 313 363 304 306 307 308 309)

for n in "${CHAIN[@]}"; do
    state=$(gh pr view "$n" --json state -q .state 2>/dev/null)
    if [[ "$state" == "MERGED" ]]; then
        echo "── #$n already merged, skipping"
        continue
    fi

    echo
    echo "════════════════════════════════════════════════"
    echo "  #$n  $(gh pr view "$n" --json title -q .title)"
    echo "════════════════════════════════════════════════"

    if [[ "$state" == "CLOSED" ]]; then
        echo "   ✗ #$n is CLOSED — reopen it and set its base to staging first"
        echo "     (deleting a base branch on merge auto-closes anything stacked on it)"
        exit 1
    fi

    base=$(gh pr view "$n" --json baseRefName -q .baseRefName)
    if [[ "$base" != "staging" ]]; then
        echo "   retargeting #$n from $base to staging"
        gh pr edit "$n" --base staging >/dev/null
    fi

    branch=$(gh pr view "$n" --json headRefName -q .headRefName)
    prev_sha=$(gh pr view "$n" --json headRefOid -q .headRefOid)

    upd=$(gh pr update-branch "$n" 2>&1)
    if grep -qiE 'up.to.date|not.*behind|no changes' <<<"$upd"; then
        echo "   already up to date"
        head_sha="$prev_sha"
    else
        echo "   branch updated"
        # Reading headRefOid immediately after update-branch returns the OLD
        # sha — the API is eventually consistent. Poll until it actually moves,
        # or we match a run for the previous commit. That is how #304 "failed"
        # on a run from four days earlier.
        echo -n "   waiting for new head"
        head_sha="$prev_sha"
        for _ in $(seq 1 24); do
            sleep 5
            echo -n "."
            head_sha=$(gh pr view "$n" --json headRefOid -q .headRefOid)
            [[ "$head_sha" != "$prev_sha" ]] && break
        done
        echo " ${head_sha:0:7}"
        if [[ "$head_sha" == "$prev_sha" ]]; then
            echo "   ! head never moved; treating $prev_sha as current"
        fi
    fi

    echo -n "   waiting for CI on ${head_sha:0:7}"
    run_id=""
    for _ in $(seq 1 24); do
        sleep 5
        echo -n "."
        run_id=$(gh run list --branch "$branch" --limit 15 \
                 --json databaseId,headSha \
                 -q "[.[] | select(.headSha==\"$head_sha\")][0].databaseId" 2>/dev/null)
        [[ -n "$run_id" && "$run_id" != "null" ]] && break
        run_id=""
    done
    echo

    if [[ -z "$run_id" ]]; then
        echo "   ✗ no CI run for $branch @ ${head_sha:0:7} after 2 min — stopping"
        echo "     (a closed PR or a branch with no workflow will look like this)"
        exit 1
    fi

    if gh run watch "$run_id" --exit-status >/dev/null 2>&1; then
        if gh pr merge "$n" --squash --delete-branch; then
            echo "   ✓ #$n merged"
        else
            echo "   ✗ #$n green but merge refused — check review/protection"
            exit 1
        fi
    else
        started=$(gh run view "$run_id" --json createdAt -q .createdAt 2>/dev/null)
        echo "   ✗ #$n CI FAILED — stopping so nothing stacks on it"
        echo "     run $run_id, started $started, sha ${head_sha:0:7}"
        echo "     (if that timestamp is not from the last few minutes, it is a"
        echo "      stale run and the real problem is sha matching, not the code)"
        echo
        gh run view "$run_id" --log-failed 2>/dev/null \
            | grep -vE 'UNKNOWN STEP' \
            | grep -E '(FAILED|ERROR at|✗|KeyError|^E |IntegrityError|Violation)' | head -15
        exit 1
    fi
done

echo
echo "════════════════════════════════════════════════"
echo "  chain complete — head should now be 0031"
echo "════════════════════════════════════════════════"
cd "$(git rev-parse --show-toplevel)/backend" 2>/dev/null \
    && python3 scripts/check_migration_integrity.py .. 2>/dev/null
echo
echo "Next: unpark 0032/0033/0034 (they already chain off 0031)."
