# W7 — Performance & index review (BA-W7-02)

## Redis caching (done)
`backend/app/common/cache.py` — `@cached(prefix, ttl)` decorator + `invalidate(prefix)`.
Applied to read-mostly lookups: facility capabilities, department/room lists, ICD search.
Rule: cache reads, `invalidate()` on the matching write.

## N+1 review checklist (run per module before W7 sign-off)
- [ ] patients history — batch visit/encounter/order reads (no per-row query in a loop)
- [ ] queue board — single query per department, not per token
- [ ] billing invoice view — items eager-loaded with the invoice (`selectinload`)
- [ ] lab/radiology worklist — join order + accession, don't lazy-load per row

## Index review (verify these exist; schema §3 + index addendum)
- [ ] every FK column has `ix_<table>_<col>` (Postgres does not auto-index FKs)
- [ ] `ix_visits_patient_id_visit_date`, `ix_orders_order_type_status`
- [ ] `audit_logs` / `data_access_log` partitioned indexes on (user_id, …), (patient_id, …)
- [ ] `ix_inventory_batches_fefo` partial WHERE quantity > 0
- [ ] partial unique for `is_current` (results/dispenses) and `deleted_at IS NULL` (uhid)
- [ ] BRIN on created_at/accessed_at inside audit partitions

Method: `EXPLAIN (ANALYZE, BUFFERS)` the top 10 endpoints under seeded load; any
Seq Scan on a >10k-row table is a finding.
