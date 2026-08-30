# Manual test guide — every screen, every role

Built from `frontend/src/lib/auth/routes.ts` and the actual page routes, not
from memory. If a route below does not match the app, the route table changed
and this file is stale — fix it here rather than working around it.

---

## Credentials — all thirteen roles

**Every account uses the password `devpass`.** Created by `scripts/dev_setup.sh`
against the Keycloak realm `healthdoc`; the realm role is what the app reads
from the token to decide which workspace you get.

Dev-only. These exist because CI needs deterministic identities — they are not
secrets and they are not present in any production realm.

| # | Username | Realm role | Lands on | Also reachable |
|---|---|---|---|---|
| 1 | `dev.receptionist` | `receptionist` | `/receptionist/registration` | `/receptionist/*`, `/billing`, `/consent` |
| 2 | `dev.doctor` | `doctor` | `/doctor/dashboard` | `/doctor/*`, `/consent`, `/ipd`, `/lab`, `/radiology` |
| 3 | `dev.nurse` | `nurse` | `/nurse/ward-dashboard` | `/nurse/*`, `/ipd`, `/consent` |
| 4 | `dev.labtech` | `lab_tech` | `/lab` | `/admin/maintenance` |
| 5 | `dev.radiology` | `radiology_tech` | `/radiology` | `/admin/maintenance` |
| 6 | `dev.pharmacist` | `pharmacist` | `/pharmacy/prescription-queue` | `/pharmacy/*`, `/inventory` |
| 7 | `dev.hod` | `hod` | `/hod` | `/queue-display`, `/inventory` |
| 8 | `dev.emergency` | `emergency` | `/emergency` | — |
| 9 | `dev.supervisor` | `supervisor` | `/supervisor/merges` | `/reports` |
| 10 | `dev.admin` | `admin` | `/admin` | `/admin/*`, `/billing`, `/reports`, `/audit-viewer` |
| 11 | `dev.auditor` | `auditor` | `/audit-viewer` | `/reports`, `/admin/data-protection` |
| 12 | `dev.patient` | `patient` | `/patient-portal` | — |
| 13 | `dev.superadmin` | `superadmin` | `/superadmin` | Platform facility directory only; no clinical routes |

### Other consoles

| What | Where | Credentials |
|---|---|---|
| Keycloak admin | http://localhost:8081/auth | `admin` / see `KEYCLOAK_ADMIN_PASSWORD` in `.env` |
| MinIO console | http://localhost:9001 | see `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` in `.env` |
| Orthanc (imaging) | http://localhost:8042 | see `ORTHANC_USER` / `ORTHANC_PASSWORD` in `.env` |
| Postgres | `localhost:55432` | see `POSTGRES_USER` / `POSTGRES_PASSWORD` in `.env` |
| Mongo | `localhost:57017` | — |
| Redis | `localhost:56379` | — |

### If a login fails

The usual cause is that the identities were never created. Re-run and read the
banner:

```bash
make setup   # must print "Seeded development facility and 13 authenticated users"
```

If it stops before that line, the accounts do not exist and every login will
fail. A password policy in the shared realm causes exactly this: Keycloak
enforces the policy at `kc set-password` time, and `devpass` satisfies none of
it — which is why production password rules live in
`scripts/deploy/render_keycloak_realm.py` and a test asserts the dev realm
carries no policy.

Check a specific account:

```bash
docker compose -f infra/docker-compose.yml --env-file .env exec keycloak \
  /opt/keycloak/bin/kcadm.sh get users -r healthdoc -q username=dev.hod
```


---

## 1. Start the stack

```bash
cd ~/Desktop/healthdoc
make setup        # first time, or after pulling changes to realm/seed/deps
make up           # subsequent starts
```

Wait for the banner listing thirteen dev logins. If it does not appear, nothing
below will work — read the error there first.

**App:** https://localhost — accept the self-signed certificate warning.
**Password for every account:** `devpass`

```bash
make logs                    # tail everything
docker compose -f infra/docker-compose.yml --env-file .env logs -f backend
```

Keep the backend log open in a second terminal while you click. Most failures
show there before they show on screen.

---

## 2. How to actually test a screen

A screen that renders is not a screen that works. Every defect this project
shipped rendered perfectly: `/radiology` was a title-only shell for weeks,
procurement had no list endpoint so the approval queue was merely empty, and
ABHA verification 401'd silently for months.

So on every screen, **open DevTools → Network, filter `/api/v1`**, and check:

1. **Did it call anything?** A dashboard making zero API calls is wired to
   nothing. That is the failure this catches.
2. **Any red (4xx/5xx)?** One exception: `/admin/data-protection` legitimately
   404s on `GET /dpdp/dpo` until a DPO is appointed — the screen shows a warning
   saying so. Every other 4xx is a bug.
3. **Is the list empty because there is no data, or because it is broken?**
   Empty and broken look identical. Cross-check the backend log.
4. **Does an action produce a second request?** Click the primary button. If
   the Network tab stays silent, the control is not wired.

---

## 3. Per-role walkthrough

Log out fully between roles: **click Logout in the app**, don't just clear
cookies — logout calls Keycloak's `end_session`, and skipping it leaves the SSO
session alive so the next login silently reuses the previous identity.

### dev.receptionist → lands on `/receptionist/registration`

| Screen | Expect |
|---|---|
| `/receptionist/registration` | Form renders. No API call on load is correct here. |
| `/receptionist/patient-search` | No call until you search. Type a name, expect `POST /patients/search`. |
| `/receptionist/queue` | Calls on load. |
| `/billing` | Calls on load. |
| `/consent` | Search a patient, then expect `GET /consent/patients/{id}/records`. |

**Negative:** navigate to `/admin` → must redirect, not render.

### dev.doctor → `/doctor/dashboard`

`/doctor/dashboard`, `/doctor/orders`, `/doctor/prescriptions`,
`/doctor/results`, `/doctor/pharmacy-approvals`, `/lab`, `/radiology`, `/ipd`,
`/consent` — all should call on load.

`/doctor/consultation` with no patient selected shows "Open a patient from the
live OPD queue" and makes **no** call. That is correct, not a failure.

**The order flow is worth driving end to end:** place an order from
`/doctor/orders`, then confirm it appears in `/lab` or `/radiology`. That path
had a dead-end for weeks — the workflow broke at its first step.

### dev.nurse → `/nurse/ward-dashboard`

`/nurse/ward-dashboard`, `/nurse/emar`, `/ipd`, `/consent`.

On eMAR, check a medication administration actually posts. The ward dashboard
reads fine even when writes fail.

### dev.labtech → `/lab`

`/lab`, `/admin/maintenance`.

Maintenance is deliberately writable by technicians. Record a service entry and
**leave downtime blank** — the history must show "not recorded", never `0`. A
run of zeros reads as flawless uptime.

### dev.radiology → `/radiology`

`/radiology`, `/admin/maintenance`. Same downtime check.

### dev.pharmacist → `/pharmacy/prescription-queue`

`/pharmacy/prescription-queue`, `/pharmacy/dispense`, `/inventory`.

`/inventory` has five tabs — **click every one**. Only reorder alerts and the
expiry tracker load on mount; the other tabs are separate components and a page
load does not exercise them.

### dev.hod → `/hod`

`/hod`, `/inventory`, `/queue-display`.

`/hod` makes five parallel reads. Before this screen existed the role had no
landing page at all, so treat any red here as significant.

Indent approval is HOD-only — approve one from `/inventory` and confirm the
status changes.

### dev.emergency → `/emergency`

Registration form; no call on mount is correct.

### dev.supervisor → `/supervisor/merges`

`/supervisor/merges`, `/reports`. Issue #221 tracks the merge/unmerge UI as a
known gap — check what is actually there against that issue before filing
anything.

### dev.admin → `/admin`

`/admin` (no call on mount), `/admin/users`, `/admin/departments`,
`/admin/permissions`, `/admin/account-requests`, `/admin/audit`,
`/audit-viewer`, `/admin/data-protection`, `/admin/maintenance`, `/reports`,
`/billing`.

`/admin/abdm-sync` is search-driven — **zero calls on mount is correct**. Enter
a patient identifier to trigger one.

On `/admin/data-protection`: appoint a DPO, raise a grievance, move it through
`under_review → resolved`. Escalating to the Data Protection Board asks for a
reason — confirm it refuses to proceed without one.

### dev.auditor → `/audit-viewer`

`/audit-viewer`, `/reports`, `/admin/data-protection`.

The auditor sees governance but **must not** get the staff directory. Names may
show as UUIDs here; that is deliberate — granting auditors `GET /users` to
prettify a label would widen their access.

### dev.patient → `/patient-portal`

Only this. Confirm `/receptionist/registration` redirects away.

### dev.superadmin → `/superadmin`

The platform facility directory must call `GET /api/v1/platform/facilities` and
render the returned facilities. Superadmin remains isolated from every clinical
and facility-administration route; navigating to `/admin`, `/hod`, or a patient
workspace must redirect away.

---

## 4. Negative tests — the ones that matter for the audit

These are what a WASA assessor probes. Worth doing once deliberately.

**Cross-role.** As `dev.nurse`, navigate to `/admin/users`. Expect a redirect.
Then call the API directly with the nurse's token — the UI hiding a screen is
not access control; the endpoint must refuse it too.

**Cross-facility.** The seed has one facility, so this needs a second one to
test properly. The rule: another facility's record returns **404, not 403**. A
403 confirms the record exists and lets someone enumerate patients.

**Token expiry.** Leave a tab idle past token lifetime, then act. Expect a
clean re-auth, not a wall of 401s.

**Logout.** After logging out, press Back. The previous screen must not render
with live data.

---

## 5. When something fails

```bash
# backend, with the request that failed
docker compose -f infra/docker-compose.yml --env-file .env logs --tail=100 backend

# is the endpoint even mounted?
curl -sk https://localhost/api/v1/openapi.json | python3 -m json.tool | grep -A2 '"/your/path"'

# does the frontend call an endpoint that exists?
make contract
```

`make contract` is the fast check for "the screen calls a route the backend does
not have" — a whole class of failure that looks like a broken screen.

---

## 6. What this cannot tell you

Manual clicking proves screens load and calls succeed. It does not prove the
data is *correct* — that an invoice totals right, that a stock ledger
reconciles, that an audit chain is unbroken. Those live in `make test-pg`, and a
green manual pass with a red suite means the suite is right.

Four things in this build are deliberately inert and will look broken. All of
them answer with a reason rather than failing obscurely, and all of them are
waiting on ABDM sandbox credentials rather than on code:

- **ABHA verification** — `_VERIFY_PATH` is `None` until the v3 path is
  confirmed against the sandbox, so every ABHA records as unverified.
- **ABDM M1 enrolment** — needs `ABDM_PUBLIC_KEY_PEM` and real sandbox
  credentials. Without them the endpoints answer 503 with a clear reason rather
  than sending an Aadhaar number in the clear.
- **ABDM M2/M3 gateway callbacks** — `/abdm/hip/callbacks/*` and
  `/abdm/hiu/callbacks/*` answer **503** while `ABDM_CALLBACK_SHARED_SECRET` is
  unset. That is deliberate and is the safe direction: an unauthenticated
  inbound route that writes consent artefacts and moves patient data is the
  worst thing in this integration, so not-configured means refuse. Do not file
  the 503 as a bug.
- **The `/superadmin` workspace** shows facility metadata only. It is supposed
  to: `dev.superadmin` is denied every facility and clinical route by design,
  and `e2e/superadmin-isolation.smoke.mjs` proves it.

Two reports from the earlier manual round were re-tested in a real browser and
closed as **not defects** — do not re-file them:

- `dev.emergency` 403 on `POST /patients`. The `/emergency` screen calls
  `POST /emergency/patients`, which grants the role and returns 201. The 403 is
  real, correct and unreachable: `/emergency` is the only route that role has.
- Every API call firing twice. React StrictMode double-invoke, dev only —
  1x per call on a production build, verified on the same three screens.
