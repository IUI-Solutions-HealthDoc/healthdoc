# Authenticated OWASP ZAP API scan

## Verified run — 24 August 2026

The local disposable compose stack was scanned with the official ZAP 2.17.0
image (`sha256:781a2bdaea47324e7bab583e2263f21d257b0aee61ed51521a5be45f5f5081ef`).
The scan ran from the `security-zap` working tree based on staging commit
`556a3d9`.

Authentication was not mocked. Puppeteer completed the public-client PKCE flow
as `dev.admin`, observed a bearer-authenticated `GET /api/v1/users` returning
200, verified `silent-check-sso.html` returned 200, and wrote the ephemeral
Authorization header to a mode-0600 temporary file. The runner separately
required `GET /api/v1/users/me` to return 200 before starting ZAP. The token was
removed on exit and excluded from all reports.

Before active scanning, `backup_postgres.sh` created a custom-format dump and
proved it readable with `pg_restore --list`.

| Result | Count |
|---|---:|
| OpenAPI URLs imported | 291 |
| URLs exercised | 659 |
| High / Critical alerts | **0** |
| Medium alert classes | 2 |
| Low alert classes | 6 |
| Informational alert classes | 3 |

The release gate passed because issue #242 requires zero High/Critical alerts.
The two Medium classes were malformed-input 500 responses and debug/error
disclosure derived from them. They are retained as input to the P0/P1 sweep
(#240); they are not allowlisted or relabelled. Direct-backend header findings
are also retained in the report: Nginx supplies the edge security headers, and
TLS/edge verification remains part of #244.

## Reproduce

Run `./scripts/security/run_zap_api_scan.sh` from the repository root with the
local compose stack running. Reports and the pre-scan backup are written under
the ignored `backups/zap/` directory. The Wednesday schedule and manual trigger
in `.github/workflows/zap-security.yml` repeat the same authenticated gate.

## P0/P1 hardening rerun — 24 August 2026

Issue #240's final rerun imported 292 OpenAPI URLs and exercised 661 URLs after
the malformed-input fixes. It reported:

- **zero** server-error, debug-disclosure, format-string, High or Critical findings;
- one Medium false positive matching prose in `openapi.json` (not SQL source);
- one Low content-type class covering the intentional CSV export and SSE stream.

The evidence is under ignored local artifacts at
`backups/zap/p0-hardening-final-20260824/`. This rerun is the proof that all 18
prior HTTP 500 instances were removed, not merely downgraded or allowlisted.
