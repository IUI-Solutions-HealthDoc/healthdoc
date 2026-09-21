# Branch reconciliation and release handoff — 21 September 2026

Scope: publish remaining work from the HealthDoc branches used in this thread,
without resurrecting superseded implementation or claiming clinical acceptance.

**Promotion follow-up:** #588 was approved and all four checks passed on `2fac6ff`
(run 35600175817), then it was squash-merged as `f96321d`. The source tree is
unchanged from that tested head, but the main-parent repair was lost. #589 is
the approved, conflicting staging-to-main PR. `fix/promotion-589-history`
restores the same proven main ancestry, without an application change, and adds
the [next-agent prompt](next-agent-completion-prompt-2026-09-21.md). Merge this
repair and #589 with merge commits. Verify final PR states before claiming a
completed promotion; the notes below describe their preparation-time baseline.

## Verified baseline

- Remote staging: `5771931` (#587 squash).
- Remote main: `9222f07` (#585 promotion).
- #584 safety changes are integrated through staging/main.
- #586 atomic retries/page states and #587 M1 resend/Aadhaar verification are
  merged into staging with all four CI jobs green; not yet promoted to main.
- #587 application CI: run **35584677794**, 2104 backend passes / 7 warnings,
  36 script passes, 165 frontend passes; full browser job green, weekly Electron
  skipped. Synthetic/intercepted tests are not a completed NHA exchange.
- The old local M1 branch (`ba363df`) has an identical committed tree to staging.
  The retry branch (`3b3b942`) has an identical tree to its squash `c0113dc`.
  Differences from the older safety branch to `c0113dc` are documentation only;
  its extra clinical/page-state code was already incorporated in #586.

## Reconciliation

| Branch or group | Disposition |
|---|---|
| `fix/clinical-safety-keycloak-return` | #584 then #586 contain its source fixes; do not reopen an old branch PR. |
| `fix/clinical-write-retry-safety` | Entire tree included through #586. |
| `feat/abdm-m1-desk-otp-resend-aadhaar-verify` | Entire committed tree included through #587; remaining working edits carried to this consolidation. |
| `review/project-status-2026-09-19` | Unique full review recovered as `docs/project-review-2026-09-19.md` with a historical banner. Its old leading CLAUDE/change-log summaries are superseded by later reviews, not restored over current notes. |
| `feat/suite-9-portal-terminology-a11y-m1` | Squash #583; subsequent safety fixes retained. Original checkout preserved. |
| `feat/suite-5-emar-ed-triage-lab-urgency` | Squash #573; subsequent safety fixes retained. |
| `feat/login-split-screen-hims-branding` | #563 and patch-equivalent history; its later direct-grant behavior was deliberately superseded by native PKCE safety fixes. |
| `feat/b7-audit-append-only-triggers` | Merged #261; current audit implementation retained. |
| `fix/0003a-facilities-fixes` | Merged #302; never restore old versions of already-applied migrations. |
| `feat/b6-pharmacy-queue-search-dispense` | Closed #270 explicitly superseded by #277, which includes queue/search/dispense plus substitution. Old branch not merged again. |
| `feat/b1-ajay` | Closed #264 explicitly superseded by split PRs #302–313. Closing review rejects enum/module/ICD/checker reversions and duplicate migration. Current cache/dev setup exists. This is not an unpublished release branch; do not resurrect rejected changes. |

The following local branch heads are already ancestors of current staging:

- `chore/close-verified-issues`
- `feat/billing-authority-and-nursing-handover`
- `feat/billing-tariff-management`
- `feat/external-referral-results`
- `feat/reception-consent-nurse-task-safety`
- `feat/suite-1-core-arrival-safety`
- `feat/suite-6-critical-alerts-lis-pacs-inventory`
- `feat/suite-8-immunization-blood-forms-walkin`
- `feat/ui-modernization-and-audit-pagination`
- `fix/abdm-historical-registration`
- `fix/abdm-live-operations`
- `fix/abdm-milestone-closure`
- `fix/abdm-otp-live-verification`
- `fix/auth-direct-grant-tab-session-restore`
- `fix/billing-abdm-readiness`
- `fix/billing-dashboard-validation-and-invoice-list`
- `fix/billing-invoice-switch-safety`
- `fix/billing-tariffs-patient-safety`
- `fix/ci-minio-registry`
- `fix/external-result-input`
- `fix/tariff-write-safety`
- local `main` and `staging` (these local pointers are older than the remotes).

## New publication contents

1. Actionable duplicate-ABHA refusal instead of misleading generic reload copy,
   with an error-policy regression.
2. Operator-recorded 21 September M1 case updates, with local patient identifier
   redacted. Existing PASS/PARTIAL/GAP distinctions and unpassed M2/M3 retained.
3. Support draft reconciled with the owner's report of another submitted ticket;
   actual ticket number/submitted text/response not independently verified.
4. Historical review recovered, and current CLAUDE/acceptance/change notes updated.

No new migration, application deployment, OTP/token request, clinical transfer,
worker start or certification action is part of this publication.

The original checkout's four untracked comparison PDFs, `Issues/Updates.md` and
`backend/uv.lock` remain untouched as local inputs/unrelated lockfile. They are
not automatically staged by a broad `git add`; secrets, raw clinical evidence,
node_modules and environment files are excluded. Historical remote branch refs
are not recreated merely to duplicate content already present in staging.

## Release gates

- Follow-up branch: **release/staging-consolidation**.
- Fresh local checks on this consolidation: **166 frontend tests**, **89 focused
  backend tests**, TypeScript and changed-source ESLint passed; diff check clean.
  Check the follow-up PR's own complete CI after push.
- Staging protection requires up-to-date checks and one code-owner approval.
  No bypass/admin merge is permitted. User approval in chat is not a substitute
  for the GitHub-required code-owner review.
- After the follow-up is approved and merged, create **staging -> main** so the
  promotion contains both #586/#587 and this consolidation. Do not represent a
  promotion opened before integration as containing these local changes.
- All-suite and M1/M2/M3 acceptance remain open as detailed in the current
  [ten-suite ledger](ten-suite-acceptance-status-2026-09-20.md).

## Promotion history repair

A read-only merge simulation of staging/main found 23 conflicted files caused
by the previous squash promotion history. There is no unique main application
change to recover: `origin/main` (`9222f07`) and the already-integrated staging
revision `dcd7d15` have the exact same tree,
`2ca4bada305dd4d7b0e1b46b613483d4a8d4924d`; `dcd7d15` is an ancestor of staging.

The consolidation therefore records main as a merge parent while retaining the
current staging-plus-follow-up tree. This is a history-only merge (`-s ours`),
not a conflict resolution that discards unknown main changes. Recheck those
tree/ancestry facts immediately before doing it and verify its before/after
trees are identical.

**Merge this consolidation PR into staging with a merge commit, not squash or
rebase.** The main-parent ancestry must survive integration; otherwise the same
promotion conflicts return. The later staging-to-main PR must also use a merge
commit when approved, to keep the long-lived branch histories connected.
