# ADR 0002: Full Departmental Billing

## Status
Accepted — 2026-07. Supersedes the billing portion of ADR 0001.
The identity-path model (§2 of ADR 0001) and mandatory photo capture (§3) REMAIN in force.

## Context
ADR 0001 replaced departmental billing with a single one-time registration payment.
Project scope has changed again: departmental billing is back in.

## Decision
1. **Every visit gets exactly one invoice**, created at registration with the
   registration fee as its first line item. Departments (lab, radiology, pharmacy,
   procedures, IPD) append `invoice_items` as chargeable work completes.
2. **Invoices are immutable once issued** — a DB trigger blocks updates to financial
   columns after `status` leaves `draft`. Corrections = cancel + new invoice.
3. **Partial payments allowed** (many `payments` rows per invoice). Refunds are
   reversal rows against a payment, never edits.
4. **Government schemes** are modeled as `scheme_adjustment` on the invoice
   (full waiver ⇒ status `waived`), not as a payment mode.
5. **Clinical fulfilment is NOT payment-gated.** Orders proceed regardless of invoice
   state; billing accrues in parallel. IPD discharge checks settlement per facility
   policy but is never hard-blocked for emergency/DAMA cases.
6. **Gapless numbering** for invoice/receipt/refund numbers via `billing_counters`
   with `SELECT ... FOR UPDATE` (financial audit requirement).
7. Collection is performed by the Receptionist role for now; a dedicated
   cashier/billing Keycloak role can be added later without schema change.

## Consequences
- Migration 0014 = invoices, invoice_items, payments, refunds, billing_counters
  (replaces the registration_payments design). See docs/database-schema.md §3.
- `registration_payments` / `registration_refunds` are never created.
- backend module `billing/` and frontend `app/billing/` are active modules again.
- Invoices/payments keep CRITICAL sync sensitivity — never auto-resolved.

## References
- docs/database-schema.md §2 (0014), §3, §4.4 · docs/schema-conventions.md §7
