#!/usr/bin/env bash
# Creates the three v3.14 gap issues. Run once, from the repo root.
set -euo pipefail
cd "$(dirname "$0")/.."

gh issue create --title "[B3] 0032 — allergies table + server-side prescribing gate" --label "backend,schema,patient-safety" --body "$(cat <<'EOF'
Spec: `docs/database-schema.md` §3 **0032 — allergies**.

Today an allergy is free text in a consultation note, so the prescribing screen has
nothing to check against. This is the most common preventable medication harm in a
hospital system, and NABH requires it documented.

## Scope
- [ ] Migration 0032: `allergies` table exactly as specced (`[Blame]`, `row_version`, `INDEX (patient_id, status)`)
- [ ] Same migration: `ALTER inventory_items ADD ingredient_code varchar(50) NULL` + index
- [ ] `AllergenType` / `AllergySeverity` / `AllergyStatus` are already in `common/enums.py` — use `.sql_check()`, do not hardcode
- [ ] `GET /patients/{id}/allergies`
- [ ] `POST /patients/{id}/allergies` (Idempotency-Key), `PATCH` with If-Match
- [ ] Prescribing gate on `POST /prescriptions/{id}/items`

## Acceptance criteria
- [ ] Matching is on **`ingredient_code`, not `inventory_item_id`** — a penicillin allergy triggers on amoxicillin. Test this explicitly with two different `inventory_items` rows sharing an ingredient code.
- [ ] `severity = 'anaphylaxis'` returns `409 allergy_conflict` and **cannot be overridden by any role**. Test asserts no role can force it.
- [ ] Other severities are overridable with `override_reason` >= 20 chars; the reason lands on `prescription_items.allergy_override_reason` AND `audit_logs`, same transaction.
- [ ] An allergy with `ingredient_code IS NULL` is display-only and the response marks it as such — it must never silently fail to match.
- [ ] Records are never hard-deleted; correction sets `status = 'entered_in_error'`.
- [ ] Facility-scoped: the patient must belong to the caller's facility.

## Explicitly out of scope
Drug–drug interaction checking. It needs a licensed interaction database, and a partial
implementation that misses interactions is more dangerous than none because clinicians
calibrate trust to what the system claims to do. Separate ticket if/when we license one.
EOF
)"

gh issue create --title "[B7] 0033 — charge_master + idempotent charge accrual" --label "backend,schema,billing" --body "$(cat <<'EOF'
Spec: `docs/database-schema.md` §3 **0033 — charge_master**.

`invoice_items.unit_price` is currently typed by whoever creates the line: two clerks
charge different amounts for the same test, "what was the tariff on 12 March" is
unanswerable, and PM-JAY rates are mandated — so an overcharge is a compliance breach,
not a pricing mistake.

## Scope
- [ ] Migration 0033: `charge_master` (effective-dated, `scheme_code`, the `effective_to > effective_from` CHECK)
- [ ] `ALTER invoice_items ADD charge_master_id UUID NULL -> charge_master`
- [ ] `ALTER invoice_items ADD CONSTRAINT uq_invoice_items_source UNIQUE (invoice_id, reference_type, reference_id)`
- [ ] Charge accrual service: completed order item / dispense / bed-day / procedure -> invoice line

## Acceptance criteria
- [ ] **Double-billing is structurally impossible.** Test: finalise the same lab result twice, assert exactly one invoice line. This is the single most important criterion here.
- [ ] `unit_price` is copied onto the line at accrual time, never joined at read time — a tariff revision must not alter an already-issued invoice. Test with a price change between accrual and read.
- [ ] Bed-day accrual uses the **facility business date** `(now() AT TIME ZONE facilities.timezone)::date`, not UTC. Test at 00:30 IST.
- [ ] Scheme rate wins over general tariff when `invoices.scheme_code` is set.
- [ ] No matching tariff -> `409 no_tariff`. Never a zero-rupee line.
- [ ] A price is superseded by inserting a new row, never by UPDATE. Test that price history is reconstructible for any past date.
EOF
)"

gh issue create --title "[B4] 0034 — one active admission per bed + transfer destination" --label "backend,schema" --body "$(cat <<'EOF'
Spec: `docs/database-schema.md` §3 **0034 — IPD bed integrity**.

One-active-admission-per-bed is currently enforced only in the service layer, so one bug
double-books a bed and the second admission looks valid.

## Scope
- [ ] Migration 0034:
```sql
CREATE UNIQUE INDEX uq_admissions_active_bed
  ON admissions (bed_id) WHERE status = 'admitted';
```
- [ ] `ALTER discharges ADD destination_facility_id UUID NULL -> facilities`
- [ ] `ALTER discharges ADD destination_facility_name text NULL`
- [ ] CHECK: `discharge_type <> 'transferred' OR destination_facility_id IS NOT NULL OR destination_facility_name IS NOT NULL`
- [ ] Reconciliation job for `beds.status` vs active admissions

## Acceptance criteria
- [ ] Test opens two concurrent sessions admitting to the same bed; exactly one succeeds and the other gets a clean `409 bed_occupied`, not a 500.
- [ ] `beds.status` is updated in the **same transaction** as the admission — `admissions` is authoritative, `beds.status` is a mirror.
- [ ] Reconciliation job flags any bed whose status disagrees with its active admission; test seeds a deliberate mismatch.
- [ ] A `transferred` discharge without any destination is rejected at the DB level.
EOF
)"

echo
echo "✓ three issues created"
