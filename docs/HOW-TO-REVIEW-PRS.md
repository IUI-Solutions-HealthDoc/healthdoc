# Reviewing team PRs — the loop

All 13 devs branch off `staging` and open PRs into `staging`. You review from your
machine with your main account. CODEOWNERS is centralised, so an approval from
`@solutionsiui` or `@kandol007` unblocks a merge.

---

## 1. See what's waiting

```bash
./scripts/pr-triage.sh            # every open PR → staging
./scripts/pr-triage.sh --mine     # only those still awaiting review
```

For each PR it prints author, size, CI state, review state, whether it's backend or
frontend, and **the exact review command to run next**.

## 2. Review one

```bash
./scripts/review-backend-pr.sh 261        # or review-frontend-pr.sh
./scripts/review-backend-pr.sh 261 --post # also posts the verdict as a comment
```

The script checks out the PR, runs every gate, prints a verdict, and puts your branch
back. Then you judge the things it can't (it prints that list at the end).

## 3. Decide

### If it's good

```bash
gh pr review 261 --approve --body "Reviewed: migration 0006 matches §3, enum values synced,
audit write in the same transaction, tests included. Approved."
```

### If something's wrong → **request changes on the SAME PR**

```bash
# write the review, then:
gh pr review 261 --request-changes --body-file /tmp/review.md
```

The dev pushes fixes to the **same branch**; the PR updates automatically, CI re-runs,
and you re-review. **Do not ask for a new PR for ordinary fixes** — you would lose the
review thread, the discussion, and the commit history, and it makes the same work look
like two deliverables.

### When a NEW PR genuinely is the right call

Only these:

| Situation | Why a new PR |
|---|---|
| Wrong base branch (targets `main`, not `staging`) | base can be edited, but if commits are tangled, start clean |
| PR contains several unrelated modules | ask them to split — one module per PR keeps reviews ≤400 lines |
| Branch history is broken (merged the wrong thing, force-pushed over others' work) | history can't be untangled safely |
| Branch was created from another dev's feature branch instead of `staging` | it will drag in unmerged work |

Template for that case:

```bash
gh pr close 261 --comment "Closing in favour of a clean PR — this branch was cut from
feat/other-work rather than staging, so it carries unmerged commits. Please:
  git checkout staging && git pull
  git checkout -b feat/<you>-<module>-<desc>
  git cherry-pick <your commits>
and open a fresh PR. Your review comments are preserved here for reference."
```

## 4. Merge

```bash
gh pr merge 261 --squash --delete-branch
```

Squash keeps `staging` history one-commit-per-PR. Then locally:

```bash
git checkout staging && git pull
```

**Do this after every merge** — it's what prevents the divergence that causes conflicts
on your next branch.

---

## Writing the request-changes body

Lead with the blockers, be specific about the fix, and say what's good. Template:

```markdown
Thanks — <what genuinely works well>.

**Blockers**
1. <file:line> — <what's wrong>. <the fix>. (<convention ref>)
2. ...

**Should fix in this PR**
3. ...

**Note (fine to defer)**
- <thing that belongs in a follow-up issue>

Push to this branch and I'll re-review — no need for a new PR.
```

That last line matters: devs often assume rejection means starting over.

---

## Merge order for migrations

Migrations must merge in **chain order** (0003 → 0004 → 0005 …). If B7's 0003 and B2's
0006 are both approved, merge 0003 first. `check_migration_integrity.py` fails the build
on a fork, but ordering across separate PRs is a human call — check the migration map in
`docs/database-schema.md` §2 before merging two at once.
