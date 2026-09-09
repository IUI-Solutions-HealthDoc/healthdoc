# Bahmni evaluation: repository plan, local runtime and HealthDoc comparison

Reviewed **7 September 2026**. “Our project” means **HealthDoc**, not the DMRD files currently open in the IDE. HealthDoc baseline: `34fac43`. Bahmni checkout root: `/Users/ritikkumar/Desktop/Bahmni`.

## Recommendation

**Run Bahmni Standard from the `bahmni-docker` repository you already have. No additional source clone is required for its packaged runtime.** Add source repositories selectively to study workflows. Use a separate India distribution for ABDM research; Standard does not implicitly include its HIP/HIU services. Docker is Bahmni's [recommended installation method](https://www.bahmni.org/install).

This is an architecture, distribution, repository and feature review—not a line-by-line audit of every repository or a completed Bahmni browser test. I inspected the five local checkouts, current public organization inventories, selected source/manifests, image architectures, official feature documentation and relevant HealthDoc modules/evidence. **No repositories were cloned/pulled, no images downloaded, no Bahmni services started, and no running project stopped.**

## 1. What you already cloned

All five working trees were clean at inspection. Commit IDs describe the inspected files; they are not a claim that each branch is the latest remote revision.

| Existing repository | Inspected commit | Purpose | Needed to run prebuilt Standard? |
|---|---|---|---|
| `bahmni-docker` | `c32e9a6` | Compose distribution, images, profiles, backup/restore utilities | **Yes: the entry point** |
| `bahmni-core` | `04a5299ed` | OpenMRS extensions and EMR/integration services | No source build; packaged modules are in the image |
| `openmrs-module-bahmniapps` | `24ec65d9a` | Existing AngularJS/React EMR frontend | No source build; packaged frontend image |
| `bahmni-module-fhir2-addl-extension` | `046d889` | Additional OpenMRS FHIR2 implementation extensions | No separate startup; not the ABDM HIP/HIU system |
| `bahmni-module-immunization` | `b59b382` | FHIR Immunization support: vaccination history, products, lots, performers | No separate startup; an OpenMRS module, not a complete application |

Do not try `npm run dev` in all five folders. Java `.omod` modules load inside OpenMRS; they are not independent HTTP servers. The [OpenMRS distribution POM](https://github.com/Bahmni/openmrs-distro-bahmni/blob/master/distro/pom.xml) is the dependency/version map, including upstream OpenMRS modules. New source on `main`/`master` may not match the older published images in the runtime.

## 2. The product is a collection of integrated systems

```text
Bahmni proxy + implementation configuration
├── Clinical system: OpenMRS + MySQL + Java modules
│   ├── Existing EMR frontend (AngularJS / React)
│   ├── New React / TypeScript / Carbon frontend
│   ├── Appointments, IPD/nursing, forms and document components
│   └── Print-template service
├── Laboratory: Bahmni's OpenELIS distribution + PostgreSQL
├── Billing / stock / accounting: Odoo 16 + PostgreSQL
├── Integration workers: Atom feeds between clinical / lab / ERP systems
├── Imaging: PACS integration + DCM4CHEE / viewer + database
└── Reporting: reports service; optional Mart / Metabase

Separate India distribution
└── ABHA interface + HIP + HIU + clinician UI + event listener
    + queues / databases / OTP delivery / callback infrastructure
```

This differs from HealthDoc's Next.js/FastAPI modular monorepo, PostgreSQL domain model, Keycloak authentication, Redis, MongoDB and MinIO. Bahmni offers substantial subsystem functionality but has more application/database boundaries to configure, reconcile, back up and secure. HealthDoc's simpler integration boundary is not evidence of equal feature depth.

### Standard versus Lite

| Distribution | Appropriate comparison | Important difference |
|---|---|---|
| **Standard** | Full hospital: clinical, IPD, lab, pharmacy/stock, billing, imaging | Odoo 16 and OpenELIS in the selected distribution |
| Lite | Clinic / lightweight deployment | Crater billing and lightweight lab components; not the equivalent full ERP/lab comparison |
| India package | Study ABHA/HIP/HIU workflows | Separate composition and images; not an extra profile present in your Standard compose file |

The selected local Compose model expands to **11 services for `emr`, 21 for `bahmni-standard`, and 25 for `bahmni-standard,bahmni-mart`**. Those counts include infrastructure/configuration services, not 21 independent user applications. Standard still excludes optional SMS, terminology/CDSS and simulator profiles. Do not use `--profile '*'`: it would also select restore and legacy components. See the [official profile guide](https://bahmni.atlassian.net/wiki/spaces/BAH/pages/3117219857/Docker+Compose+Profiles).

## 3. Additional source repositories to clone

### First batch: ten highest-value repositories for the comparison

These are **source-study recommendations**, not ten missing runtime dependencies. All are under the `Bahmni` organization; repository name capitalization below is intentional.

| Repository | Default branch at review | What to examine |
|---|---|---|
| [standard-config](https://github.com/Bahmni/standard-config) | `master` | Hospital configuration, forms, concepts, dashboards, print configuration |
| [openmrs-distro-bahmni](https://github.com/Bahmni/openmrs-distro-bahmni) | `master` | Exactly which OpenMRS modules/versions are assembled; image build |
| [bahmni-apps-frontend](https://github.com/Bahmni/bahmni-apps-frontend) | `main` | Current React/TypeScript frontend, reusable clinical controls, navigation |
| [OpenElis](https://github.com/Bahmni/OpenElis) | `master` | Specimens, test panels, validation, referrals, lab reporting; inspect this packaged fork first |
| [bahmni-odoo-modules](https://github.com/Bahmni/bahmni-odoo-modules) | `main` | **Odoo 16** healthcare customizations; billing, pharmacy and inventory |
| [openerp-atomfeed-service](https://github.com/Bahmni/openerp-atomfeed-service) | `master` | Despite its older name, this produces the `odoo-connect` integration service |
| [openmrs-module-ipd-frontend](https://github.com/Bahmni/openmrs-module-ipd-frontend) | `main` | Ward/nursing workflow UI |
| [openmrs-module-ipd](https://github.com/Bahmni/openmrs-module-ipd) | `main` | IPD care/monitoring backend |
| [bahmni-reports](https://github.com/Bahmni/bahmni-reports) | `master` | Operational/clinical reports, scheduling and export patterns |
| [pacs-integration](https://github.com/Bahmni/pacs-integration) | `master` | Imaging orders, integrations, PACS/viewer packaging |

Commands to run when you decide to download these sources. Existing directories are deliberately skipped rather than reset or pulled blindly:

```bash
cd /Users/ritikkumar/Desktop/Bahmni
for repo in standard-config openmrs-distro-bahmni bahmni-apps-frontend \
  OpenElis bahmni-odoo-modules openerp-atomfeed-service \
  openmrs-module-ipd-frontend openmrs-module-ipd bahmni-reports pacs-integration
do
  if [ -e "$repo" ]; then
    printf 'Already present; inspect separately: %s\n' "$repo"
  else
    git clone --depth 1 "https://github.com/Bahmni/$repo.git" "$repo" || break
  fi
done
```

Shallow clones suit exploration. If later building a release, fetch the required tag/history and match the distribution's dependency versions; do not assemble arbitrary latest commits together.

### Second batch: clone only for the area assigned to a developer

| Area | Repositories under `Bahmni` |
|---|---|
| Configurable forms | `implementer-interface`, `form-controls`, `form2-controls` (check the consuming frontend dependency/version before selecting a controls generation) |
| Appointments / scheduling | `openmrs-module-appointments`, `openmrs-module-appointments-frontend`, `openmrs-module-teleconsultation` |
| Beds / medication administration | `openmrs-module-bedmanagement`, `openmrs-module-medicationadministration` |
| Shared clinical UI | `bahmni-clinical-components`, `bahmni-carbon-ui` |
| Lab-to-FHIR and resource APIs | `elis-fhir-result-support`, `openmrs-module-fhir2`, `openmrs-module-fhir2Extension` |
| Print and documents | `bahmni-template-service`, `patient-documents`, `patient-doc-upload-frontend`, `discharge-summary-frontend`, `fhir-pdf` |
| Analytics | `bahmni-mart`, `bahmni-metabase` |
| Patient access | `patient-portal-frontend`, `patient-portal-service` (not included in the selected Standard profile) |
| Operation theatre | `openmrs-module-operationtheater` |
| Terminology / decision support | `openmrs-module-snomed`, `openmrs-module-cdss`, `snomed-fhir-cds-service`, `snomed-bahmni-docker` (additional data/configuration requirements; reference CDS is not a clinically approved rule set) |
| Testing | `Bahmni-standard-e2e-tests`, `bahmni-ui-test-automation`, `bahmni-api-test-automation`; inspect current workflow CI and compatible app version |
| Operations | `bahmni-proxy`, `bahmni-observability`, `bahmni-decision-records`; Kubernetes `helm-charts` / `helm-umbrella-chart` only if needed |

All names were checked against the public organization inventory. Their presence is not proof of production completeness. Use `https://github.com/Bahmni/<repository>` for each entry.

**Do not prioritize:** `bahmni-docker-old`, archived `docker-bahmni`, CentOS/Vagrant/RPM setup, old `openerp-modules` / `odoo-modules` (Odoo 10), implementation-specific hospital forks, or the deprecated offline `bahmni-connect` as your main baseline. `bahmni-frontend` is not the same repository as the current `bahmni-apps-frontend`. `default-config` is not the `standard-config` image selected by this Standard compose file. [Current installer guidance](https://www.bahmni.org/install) prefers Docker over the discontinued RPM path.

## 4. ABDM: the second organization you need

The official Bahmni documentation points to **[BahmniIndiaDistro](https://github.com/BahmniIndiaDistro)**. For HealthDoc's immediate milestone gaps, study these eight repositories:

| Repository | Why relevant to HealthDoc |
|---|---|
| [bahmni-india-package](https://github.com/BahmniIndiaDistro/bahmni-india-package) | Actual India/ABDM Compose topology, service images and configuration |
| [ABHA-Verification](https://github.com/BahmniIndiaDistro/ABHA-Verification) | User-facing ABHA identity/verification workflow; use this current name rather than assuming the older `ndhm-react` name |
| [hip-service](https://github.com/BahmniIndiaDistro/hip-service) | HIP discovery/linking, consent handling, transfer orchestration |
| [openmrs-module-hip](https://github.com/BahmniIndiaDistro/openmrs-module-hip) | Clinical record adapter between OpenMRS and HIP; not directly usable against HealthDoc's schema |
| [hip-atomfeed-listener](https://github.com/BahmniIndiaDistro/hip-atomfeed-listener) | Encounter-driven HIP linking/new-context notification; useful for our missing application/event initiation |
| [health-information-user](https://github.com/BahmniIndiaDistro/health-information-user) | Consent requests, retrieval and record handling |
| [hiu-ui](https://github.com/BahmniIndiaDistro/hiu-ui) | Clinician consent/record experience; especially relevant to our missing HIU viewer |
| [hiu-db-initializer](https://github.com/BahmniIndiaDistro/hiu-db-initializer) | Receiving-service database bootstrap, referenced by the package |

Also inspect `otp_service`, `abdm-callback-proxy` and the distribution-selected India configuration repository when studying delivery/ingress. Clone them into a distinct `india` subfolder to avoid confusing their `clinic-config`/`default-config` with the main organization's variants.

```bash
mkdir -p /Users/ritikkumar/Desktop/Bahmni/india
cd /Users/ritikkumar/Desktop/Bahmni/india
for repo in bahmni-india-package ABHA-Verification hip-service openmrs-module-hip \
  hip-atomfeed-listener health-information-user hiu-ui hiu-db-initializer
do
  if [ -e "$repo" ]; then
    printf 'Already present; inspect separately: %s\n' "$repo"
  else
    git clone --depth 1 "https://github.com/BahmniIndiaDistro/$repo.git" "$repo" || break
  fi
done
```

### Critical warning: historical certification does not establish current v3 compatibility

Bahmni documents its historical ABDM completion in its [HIP/HIU overview](https://bahmni.atlassian.net/wiki/spaces/BAH/pages/2901114904). However, direct source inspection on this date found:

- HIP [`Constants.cs`](https://github.com/BahmniIndiaDistro/hip-service/blob/master/src/In.ProjectEKA.HipService/Common/Constants.cs): `CURRENT_VERSION = "v0.5"`, `UPDATED_VERSION = "v1.0"`, and ABHA `VERSION_V2 = "v2"`.
- HIU [`Constants.java`](https://github.com/BahmniIndiaDistro/health-information-user/blob/master/src/main/java/in/org/projecteka/hiu/common/Constants.java): gateway callback prefix `/v0.5`.
- The India package's recorded last push was January 2025; key HIP/HIU repos were last pushed in early 2025. Push dates alone do not prove incompatibility—the concrete old paths are the relevant evidence.
- The HIP README still names .NET Core 3.1, but its current `.csproj` targets **net8.0**. Read executable configuration rather than assuming every README is current.

**Use the workflows as reference. Do not replace our corrected v3 requests with these old paths or promise the unmodified package will pass today's sandbox.** This review did not prove that any compatibility adapter or another maintained branch resolves the mismatch. Confirm with maintainers and test against NHA's currently assigned v3 contracts.

Do not point HealthDoc's existing bridge at a Bahmni demo: that would redirect HealthDoc callbacks. Any live comparison requires explicitly isolated registration/identities and a valid HTTPS callback host. Do not reuse production data, participant OTPs or secrets between the systems. The [Bahmni ABDM Docker guide](https://bahmni.atlassian.net/wiki/spaces/BAH/pages/3148087297/) is useful topology documentation but contains dated deployment/API assumptions.

## 5. Your Mac: concrete startup constraints

| Check | Observed | Consequence |
|---|---|---|
| Host | Apple Silicon `arm64`, 16 GiB RAM | Some selected images require emulation |
| Docker | 10 CPUs, approximately 7.65 GiB assigned; Compose 5.1.1 | Several other project containers already share this memory |
| Host disk | Approximately 45 GiB available | Image extraction, DBs and backups need headroom; avoid pulling every optional stack |
| Existing ports | HealthDoc owns host 80/443; its frontend owns 3000 | Default Bahmni proxy and a default local React dev server conflict |
| Standard `.env` | `COMPOSE_PROFILES=emr` | Plain `docker compose up` does **not** start the complete hospital suite |
| Tags | Mixed component versions, including frontend `latest` | Record image digests; `.env` is not a wholly immutable release lock |
| Profiles | Standard 21 services; Standard + Mart 25 | Prefer phased evaluation or a separate adequately sized host |

Registry metadata checked without downloading layers:

| Selected image | Architecture observation |
|---|---|
| `bahmni/openmrs:1.1.2` | amd64 and arm64 |
| `bahmni/openelis:1.0.0` | amd64 and arm64 |
| `bahmni/dcm4chee:1.0.0` | amd64 and arm64 |
| `bahmni/odoo-16:1.0.0` | amd64 only |
| `bahmni/openmrs-db:1.0.0-standard` | amd64 only |
| `bahmni/odoo-16-db:1.0.0-standard` | amd64 only |
| `reportsdb` service | Compose explicitly pins `linux/amd64` |

Other selected images still require architecture verification at pull time. The Standard PACS database is pinned to `postgres:9.6`; this is an evaluation baseline, not an endorsement of its production security posture. Run a full image/dependency review before any deployment.

Bahmni's older [system requirements](https://bahmni.atlassian.net/wiki/spaces/BAH/pages/3506179/System+Requirements) describe 8 GB for testing and 16 GB with PACS. Those are not guarantees for today's image set. **My recommendation:** use a separate Linux amd64 machine/VM with at least 16 GB assigned for the full evaluation, or run one evaluation stack at a time locally after agreeing which existing projects may stop. No existing projects were stopped here.

## 6. Isolated local run plan

These commands are a plan, **not an already passing installation**. Resolve RAM/disk and verify image compatibility first. Use synthetic patients only.

### A. Add an explicit local override

In `bahmni-docker/bahmni-standard`, create `compose.local.override.yml` with this content. It keeps changes separate from upstream and binds published ports only to this machine:

```yaml
services:
  proxy:
    ports: !override
      - "127.0.0.1:8088:80"
      - "127.0.0.1:8448:443"
  openmrsdb:
    platform: linux/amd64
  odoo:
    platform: linux/amd64
    ports: !override
      - "127.0.0.1:8069:8069"
  odoodb:
    platform: linux/amd64
  dcm4chee:
    ports: !override
      - "127.0.0.1:8055:8055"
      - "127.0.0.1:11112:11112"
  ipd:
    container_name: bahmni-review-ipd
```

`!override` is important: an ordinary ports list can retain upstream 80/443 as well as adding the new ports. It requires Compose 2.24.4+; your installed version supports it. The example was checked with Compose's configuration renderer; **21 services resolved and all published ports were loopback-only, with no host 80/443 bindings**. This proves configuration merging, not runtime health. [Docker merge rules](https://docs.docker.com/reference/compose-file/merge/).

### B. Inspect the selection before downloading

```bash
cd /Users/ritikkumar/Desktop/Bahmni/bahmni-docker/bahmni-standard
export COMPOSE_PROFILES=bahmni-standard
docker compose -p bahmni-review --env-file .env \
  -f docker-compose.yml -f compose.local.override.yml config --services
docker compose -p bahmni-review --env-file .env \
  -f docker-compose.yml -f compose.local.override.yml config --images
```

Use `.env` as the packaged evaluation baseline, not `.env.dev` blindly. Pin mutable tags/digests when creating reproducible evidence. Keep environment values out of shared reports: full `docker compose config` prints expanded credentials, unlike `--services`/`--images`.

### C. Pull, start, inspect

After the resource/architecture checks:

```bash
docker compose -p bahmni-review --env-file .env \
  -f docker-compose.yml -f compose.local.override.yml pull
docker compose -p bahmni-review --env-file .env \
  -f docker-compose.yml -f compose.local.override.yml up -d
docker compose -p bahmni-review --env-file .env \
  -f docker-compose.yml -f compose.local.override.yml ps -a
docker compose -p bahmni-review --env-file .env \
  -f docker-compose.yml -f compose.local.override.yml logs --tail=100 openmrs openelis odoo odoo-connect
```

Open **`https://localhost:8448/bahmni/home/` directly**. Do not rely on `http://localhost:8088` redirecting to 8448: the inspected proxy redirect preserves `HTTP_HOST`, including the HTTP port. Handle the known local certificate warning yourself, or install a trusted local certificate. If any application link drops the port, inspect its configured public URL/redirect; a port mapping does not rewrite every absolute URL.

Use the credentials from the selected demo distribution, not HealthDoc's `dev.*` accounts. Confirm startup initialization and module loading rather than interpreting every exited one-shot configuration container as failure or every running server as healthy.

### D. Optional stages and safe stopping

- To begin more narrowly, use `COMPOSE_PROFILES=emr`; it is not a complete lab/billing comparison. Add Standard once resource availability is established.
- For BI after Standard works, use `COMPOSE_PROFILES=bahmni-standard,bahmni-mart`, then repeat pull/up with the same project name/files. This adds Mart/Metabase services.
- Keep the India/ABDM package separate, with its own project name, ports, volumes and sandbox registration. Do not mix its Compose file into Standard as an unreviewed overlay.
- Stop the evaluation with the same project/files using `stop`. Preserve named volumes. Do **not** use the helper's reset/erase option, `down -v`, or global Docker pruning to make space without reviewing exact targets.
- Never share HealthDoc database volumes, credentials or `.env` with Bahmni. Keep the proposed override local; do not accidentally publish it as an upstream production configuration.

## 7. Feature comparison: evidence versus inferred gap

Bahmni entries below describe documented/implemented capabilities, **not functionality I exercised locally today**. HealthDoc entries use inspected code plus the prior 6–7 September verification ledger. A marketing feature list, route count and screenshot count are different kinds of evidence.

| Area | Bahmni reference | HealthDoc evidence and next comparison |
|---|---|---|
| Registration / identity | Configurable demographic/identifier capture, relationships, search and cards | Registration/search/THID-UHID maker–checker paths exist and were exercised. Compare duplicate handling, identifier policies, label/card printing and relationships, not just form appearance. |
| OPD / longitudinal clinical record | Configurable forms and patient/visit dashboards; prescription regimens and prior-record views | Queue/roster, consultation, diagnosis/orders and completion have real workflow coverage. A comparable implementer form-builder platform was not established. |
| Appointments | Dedicated frontend/backend scheduling components | Day-of-service roster/token flow exists. Do not label it equivalent to appointment booking, service calendars, recurrence or teleconsultation. |
| IPD / nursing | Bed management plus IPD/care/medication modules | Admission, occupancy, vitals, SBAR handover and discharge exercised; full eMAR/fluid/approval edge cases remain broader than that evidence. Compare nursing task sequencing. |
| Laboratory | Separate OpenELIS with samples/panels, validation and external referrals | Worklist/results/MIS/referrals APIs and UI exist. Prior browser chain did not prove independent release by a second technician. Compare full request → sample → validate → amended result → doctor read-back. |
| Pharmacy / inventory | Odoo warehouses, suppliers, batches, procurement, movements and dispensing-related stock changes | PO/transfer APIs and GRN/indent/adjustment workflows exist. Not every pharmacist action/approval path is browser-proven. Compare partial quantities, returns, expiry and stock reconciliation. |
| Billing / accounting | Odoo bills, credit/discount/tax/accounting configuration and financial reporting | Build/issue/payment/admin-refund and forbidden-role flows pass. This is not proof of a complete chart of accounts, general ledger or period close equivalent. |
| Radiology / PACS | Orders to imaging systems and embedded DICOM viewing | Schedule/reschedule/cancel/report/sign-off and PACS UID exist. FHIR builder explicitly stores a study reference, not DICOM bytes. A full device/archive/viewer chain was not established. |
| Reporting / analytics | Report definitions plus separate Mart/Metabase options | Live billing/lab MIS exists. General reports read stored KPI snapshots; the snapshot producer job is still absent in inspected tracked code. This is a concrete product gap. |
| Patient portal | Separate visit/document portal repositories | Current HealthDoc portal provides verified binding, ABHA/consent and data-access history. It is not the same as a complete clinical document download/view portal; it correctly refuses unbound users. |
| Terminology / clinical content | Configurable concepts/forms and SNOMED/Snowstorm/CDSS integration | SNOMED codes in FHIR output do not establish a terminology server, configurable coded-form platform or validated clinical decision support. |
| Immunization / theatre | Dedicated source modules; package/version/UI must be verified | HealthDoc has no demonstrated immunization journey; `ot/router.py` is still a guarded ping stub. The existence of `blood_bank/` is also only a stub, not a usable workflow. No Bahmni blood-bank parity claim is made here. |
| ABDM | Separate historical ABHA/HIP/HIU implementation, including clinician UI and event listener | Our latest review found ingress, linking/initiation, viewer and recovery gaps. Bahmni's old API versions are not a ready-to-copy solution. Compare lifecycle UX and recovery, then implement against current v3 contracts. |
| Security / operations | Multiple application privilege/data boundaries, backups and observability components | HealthDoc has Keycloak roles, facility scoping, audit and maker–checker checks. Neither this comparison nor past tests certify all security, retention, recovery or multi-facility behaviour. |

Bahmni feature references: [clinical](https://www.bahmni.org/clinical-services), [lab](https://www.bahmni.org/laboratory), [stock](https://www.bahmni.org/stock-management), [billing](https://www.bahmni.org/billing-and-accounting), [PACS](https://www.bahmni.org/pacs-integration), [reporting](https://www.bahmni.org/reporting), [terminology](https://www.bahmni.org/snomed-ct-support). HealthDoc evidence: [dated billing/ABDM review](billing-abdm-readiness-2026-09-06.md), `backend/app/reports/router.py`, `backend/app/inventory/router.py`, `backend/app/radiology/router.py`, `backend/app/integrations/abdm/fhir/builder.py`, `frontend/src/app/patient-portal/page.tsx` and the role/workflow harnesses.

## 8. How to make the comparison useful

Use the same synthetic patient/story, with separate identities in each system. Record source commit, image digest, role, screen, action, persisted result, downstream result and observed defect. A screen loading is not a pass for its complete workflow.

1. **Reception + doctor:** register/search duplicates → appointment or queue → consultation → prescription/lab/imaging order → completed visit.
2. **Lab:** collect and label → enter result → independent verification → referral return → amendment → clinical read-back.
3. **Nurse + doctor:** admission → bed allocation/transfer → vitals → medication task → handover → discharge summary.
4. **Pharmacist + billing:** receive stock → partial dispense → invoice/payment → authorized refund/return → reconcile physical stock and money.
5. **Radiology:** schedule → modality worklist → synthetic image ingestion → signed report → image view from the patient's clinical record.
6. **Management:** reconcile daily financials and lab totals to real events; generate period reporting; prove blank/uncomputed is not shown as zero.
7. **Patient/HIU:** request and grant consent → retrieve → view meaningful documents → revoke/expire and prove access refusal. Separate local product demonstration from real ABDM interoperability.
8. **Operations:** restart midway through an integration, then verify retries without duplicate transactions; restore a synthetic backup and check documents/images as well as database rows.

Classify each result as **present and verified / present but not exercised / configuration required / incomplete / outside chosen distribution**. Do not assign a percentage of overall parity without a jointly agreed case list.

## 9. What to adopt, and what not to assume

Prioritize learning from **HIU clinician UX**, **clinical-event-driven context creation**, **configurable forms**, **referral/result lifecycle**, **financial reconciliation**, **PACS viewing**, and **report producers**. Preserve HealthDoc's own authorization/tenant boundaries and current v3 contracts. Replacing the stack or importing an ERP is a separate product/architecture decision, not a consequence of this review.

Licenses differ by component. The repository inventory identifies AGPL, MPL and MIT projects, with some licenses not automatically classified. **Do not copy source or rebrand components into HealthDoc without a component-level license review and preservation of required notices.** Bahmni's [license FAQ](https://www.bahmni.org/license-faq) itself asks readers to consult counsel and points to component-specific terms. Studying observable behaviour is not the same action as shipping copied code.

Practical next step: first run the isolated **Standard** evaluation, then assign the ten primary source repositories by team role. In parallel, review the eight India repositories for missing workflow design—but budget v3 adaptation and interoperability testing, not an instant certification shortcut.
