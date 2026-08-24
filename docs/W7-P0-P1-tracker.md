# W7 — P0/P1 defect tracker (BA-W7-01 / #240)

Measured against `staging` on 24 August 2026. This is an activity issue: its
deliverable is an evidenced, emptied list rather than a new product module.

| Finding | Sev | Evidence / resolution | Status |
|---|---:|---|---|
| Registration created no invoice (#389) | P0 | Invoice is created in the visit transaction; PostgreSQL journey coverage is green. | closed |
| Admissions router unreachable (#216) | P0 | `app.ipd.router` deliberately re-exports and mounts the admissions router; IPD journey is green. | closed |
| Break-glass router unregistered (#391) | P0 | Router is mounted explicitly; grant, revoke, review and consent-bypass tests are green. | closed |
| Nursing/vitals API absent (#390) | P1 | Vitals, eMAR, fluid balance, task and incident APIs are live with PostgreSQL coverage. | closed |
| Five-failure login lockout absent (#158) | P1 | Keycloak realm enforces `failureFactor=5` and a 900-second wait. | closed |
| ZAP malformed input produced 18 HTTP 500 instances | P1 | HTTP boundary rejects NUL in decoded queries/JSON; free-form route IDs are typed; department codes are bounded. Regression suite proves 400/413/422 rather than 500. | closed |
| ZAP “Format String Error” on department code | P1 | Department code now accepts only the documented code alphabet and normalises to uppercase; the exact ZAP payload is covered. | closed |
| ZAP “SQL source disclosure” in OpenAPI | — | Verified false positive: the matched text is an endpoint description telling users to select a patient ID, not SQL source or an error response. | accepted false positive |

Exit criterion: **zero open P0 and zero open P1** from CI failures,
authenticated ZAP, PostgreSQL integration tests, and reviewer-raised W1–W6
blockers. A new finding reopens the tracker; it must not be silently allowlisted.
