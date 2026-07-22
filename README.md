# HealthDoc HMIS

Hospital Information Management System for India's public health network.
ABDM V3-ready · DPDP-compliant · Offline-resilient hybrid edge-cloud.

## Repository layout

Monorepo. `backend/` (FastAPI, PostgreSQL, MongoDB, Redis), `frontend/`
(Next.js + Electron), `infra/` (Docker Compose, Nginx, Keycloak).
Module ownership is enforced via `.github/CODEOWNERS` — see
`docs/HealthDoc_Team_Tasks_GitHub.docx` for the full task plan.

## One-time GitHub setup (Tech Lead, ~15 minutes)

1. Push this repo:
   ```
   git init && git add -A && git commit -m "chore: repo skeleton"
   git branch -M main
   git remote add origin git@github-work:solutionsiui/healthdoc.git
   git push -u origin main
   git checkout -b staging && git push -u origin staging
   ```
2. Edit `.github/issues/assignees.json` — replace every placeholder with
   the real GitHub username of each developer (dev-b1 = Tech Lead, etc.).
3. Edit `.github/CODEOWNERS` — same username replacement.
4. Enable branch protection on `main` and `staging`
   (Settings → Branches: require PR, require 1 CODEOWNERS review, require CI).
5. Run the bootstrap script (needs `gh` CLI + `jq`):
   ```
   gh auth login
   ./scripts/setup_github.sh YOUR_ORG/healthdoc
   ```
   This creates all labels, 8 weekly milestones (W1–W8, each with its
   week-gate checklist in the description), and ~120 pre-assigned issues.
6. Create one GitHub Project board (Backlog / This Week / In Progress /
   In Review / Done) and add the repo's issues to it.

## Branching

- `main` — production-ready only; PRs from `staging` with Tech Lead approval
- `staging` — integration branch; auto-deploys to staging on merge
- `feat/<dev>-<module>-<desc>` — all feature work, e.g. `feat/b2-patients-search`
- `fix/<dev>-<issue#>` — bug fixes

Max 400 lines per PR. No self-merges. Migration PRs reviewed by Tech Lead.

## Week gates

Each milestone description contains the week's exit checklist.
The milestone closes only when every item is checked. Unchecked items
become `carry-over` issues in the next milestone.


## Local development

```bash
make setup   # first time: .env + dev certs + build + start + migrate
make up      # thereafter
```

Full guide: [docs/dev-setup.md](docs/dev-setup.md) — service URLs, dev logins,
module conventions, daily commands.
