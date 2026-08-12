# HealthDoc API documentation (BA-W8-01)

The API is self-documenting via FastAPI/OpenAPI — this file is the human index.

## Live references (when the stack is up)

- Swagger UI: `https://localhost/api/v1/docs`
- OpenAPI JSON: `https://localhost/api/v1/openapi.json`
- Export a static copy: `curl -k https://localhost/api/v1/openapi.json > docs/openapi.json`

## Conventions (all endpoints)

- Response envelope: `{success, data, error, meta:{request_id}}` — see `common/envelope.py`.
- Auth: `Authorization: Bearer <Keycloak JWT>`; 401 = not logged in, 403 = wrong role/ABAC deny.
- Path `{id}` params are UUIDs; business identifiers are query/body only.
- Instants use ISO-8601 UTC. Facility business dates must use
  `(now() AT TIME ZONE facilities.timezone)::date`, not a UTC calendar date.

## B1-owned surface

| Area | Endpoint(s) | Auth | Status |
|---|---|---|---|
| Health | `/api/v1/health`, `/health/deep` | public | available when the backend is running |
| Users | `/api/v1/users` CRUD, `/{id}/activate`, `/{id}/deactivate` | admin | subject to users module deployment |
| User requests | `/api/v1/user-requests` + approve/reject | admin/superadmin | pending #306 / migration chain |
| Break-glass | `/api/v1/break-glass` | emergency/doctor + MFA | not registered; blocked on 0004 and 0020 |
| ABHA link | `/api/v1/abdm/abha/link` | receptionist/doctor | pending #310 and supporting migrations |
| Capabilities | `/api/v1/facility/capabilities` | any authed | pending #304 / migration chain |

Full table of every module's endpoints: [database-schema.md](database-schema.md) section 4.4.
