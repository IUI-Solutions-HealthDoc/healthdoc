# HealthDoc on Railway

This moves the stack that runs on the owner's Mac today onto Railway, so it
stays up when the PC is off and testers, demos and the NHA sandbox reach a
stable address.

**Scope: testing, demos and the NHA sandbox, with test data only.** Railway has no India
region (the nearest is Singapore), and real patient records under ABDM and the
DPDP Act should stay on Indian infrastructure. Live hospitals go on an
Indian-region server using the existing `infra/docker-compose.prod.yml`.
Nothing here changes that file.

## Why one Railway project, not Railway + Vercel

The app is built for one origin. `/api/v1` and `/auth` are relative, the CSP is
`default-src 'self'`, and keycloak-js signs in through a same-origin
silent-SSO iframe. With the frontend on a separate Vercel domain, sign-in
hangs at "Preparing sign-in…" (CLAUDE.md, "Serving the app on a second
address"). Vercel could proxy `/api` and `/auth` back to Railway, but then the
nginx rate limits and the Keycloak admin block are lost, and every request
makes an extra hop. Every page renders per request (nonce CSP), so Vercel's
CDN would add little. Keeping nginx as the single public entry on Railway
avoids all of this with no application code changes.

## Services

Create one Railway project with region **Southeast Asia (Singapore)** for
every service. Connect the GitHub repo and set branch **`main`** for the
services built from it. **Railway deploys from `main` only**: work still
merges into `staging` first, and a merge of the reviewed staging → main
promotion is what releases it. Don't point any service at `staging`, and
don't create a second Railway environment for it. Turn on **Wait for CI**
in each repo service's settings, so a push to `main` deploys only after its
checks pass.

| Service name (exact) | Source | Root directory | Config file path | Volume | Public domain |
|---|---|---|---|---|---|
| `Postgres` | Railway PostgreSQL template | | | template's | no (TCP proxy only while migrating) |
| `KeycloakDB` | Railway PostgreSQL template | | | template's | no |
| `MongoDB` | Railway MongoDB template | | | template's | no (TCP proxy only while migrating) |
| `Redis` | Railway Redis template | | | template's | no |
| `minio` | repo | `/` | `/deploy/railway/services/minio.json` | `/data` | **yes**, port 9000 (signed download links) |
| `keycloak` | repo | `/` | `/deploy/railway/services/keycloak.json` | none | no |
| `backend` | repo | `/backend` | `/deploy/railway/services/backend.json` | optional, see note | no |
| `monitor-capture` | repo | `/backend` | `/deploy/railway/services/monitor-capture.json` | none | no |
| `frontend` | repo | `/frontend` | `/deploy/railway/services/frontend.json` | none | no |
| `edge` | repo | `/` | `/deploy/railway/services/edge.json` | optional `/var/log/healthdoc` | **yes**, port 8080, custom domain |
| `abdm-runner-dev001` | repo | `/backend` | `/deploy/railway/services/abdm-runner.json` | none | no |
| `abdm-runner-dev002` | repo | `/backend` | `/deploy/railway/services/abdm-runner.json` | none | no |

The service names matter: other services reach them as
`<name>.railway.internal`, and the `${{Name.VAR}}` references in
[`variables.example.env`](variables.example.env) use them.

What each piece replaces from the local compose stack:

- `edge` is the same nginx: the same `nginx.conf` (rate limits, log format,
  7-day log pruning) and the same locations as `prod-conf.d/healthdoc.conf`.
  Railway's edge terminates TLS, so this listens on plain `$PORT`, resolves
  upstreams through Railway's private DNS, and takes the client address from
  the last `X-Forwarded-For` entry so rate limits stay per client. It also
  closes **WASA W1** on this host by returning 404 for `/auth/admin/` and
  `/auth/realms/master/`.
- `keycloak` bakes the realm and the login theme into the image, because
  Railway cannot bind-mount files. The realm is rendered by
  `scripts/deploy/render_keycloak_realm.py` for `https://$PUBLIC_HOST`, so
  TOTP and the strong password policy are forced.
- `backend` runs `alembic upgrade head` and bucket creation as its pre-deploy
  command, which replaces the `migrate` and `minio-init` containers. A failed
  migration stops the deploy, and the old version keeps serving.
- `minio` is the same pinned source build as `infra/minio/Dockerfile.source`.
- The control room, Prometheus and Grafana are not part of this setup. The
  control room needs its own server and private TLS link, which comes later.

Note on the `backend` volume: the prod image runs as uid 10001, and Railway
volumes mount as root. To keep the audit fallback log across redeploys, attach
a volume at `/var/log/healthdoc` and set `RAILWAY_RUN_UID=0` on `backend`.
Without a volume the fallback file is lost on each redeploy. It is only written
when the audit store is unreachable.

## Steps

### 1. Accounts and domain (owner)

1. Create a Railway account and a project. **Pro** (US$20/month) is the
   right plan: Hobby caps each volume at 5 GB, which Postgres and MinIO
   outgrow, and has no team members. Both plans count the fee as usage
   credit, so at this stack's usage they bill about the same (see Cost).
2. Choose the public hostname under `healthdoc.world`, which is already on
   Cloudflare. These files use `app.healthdoc.world` as the example. Set it as the shared
   variable `PUBLIC_HOST`.

### 2. Create the services

Add the four database templates first, then the repo services from the table.
For each repo service, set **Root Directory** and **Config File Path** in its
Settings. Paste each block of `variables.example.env` into the matching
service's Raw Editor and fill every blank.

**Copy the secrets marked COPY from the PC's `.env` exactly.** If
`PII_ENCRYPTION_KEY` or the `AADHAAR_*` keys differ, encrypted fields already
in the database cannot be decrypted, and the backend may still start without
any visible error.

Don't deploy `abdm-runner-*` yet. If Railway deploys them on creation, remove
the deployment or scale the service to zero until step 7.

### 3. Freeze the PC

On the Mac, stop the app containers but leave the data stores running. The
two ABDM runners run inside the backend container, so stopping it stops them:

```bash
cd ~/Desktop/healthdoc
docker stop healthdoc-backend-1 healthdoc-frontend-1 healthdoc-nginx-1
# keep postgres, mongo, minio and keycloak running; never recreate keycloak:
# its users live only inside that container (start-dev, embedded H2)
```

From here until step 7, the PC accepts no new writes, so nothing is lost
between the dump and the restore.

### 4. Move the data

Turn on the **TCP Proxy** for `Postgres` and `MongoDB` (Settings
→ Networking) for the copy, and read each one's public URL from its
Variables tab. All commands run on the Mac.

```bash
# HealthDoc PostgreSQL. Dump in custom format, no owners: Railway's role differs.
docker exec healthdoc-postgres-1 pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-acl > healthdoc.dump
pg_restore --no-owner --no-acl --clean --if-exists -d "<Postgres DATABASE_PUBLIC_URL>" healthdoc.dump

# MongoDB
docker exec healthdoc-mongo-1 mongodump --archive --gzip -u "$MONGO_ROOT_USER" -p "$MONGO_ROOT_PASSWORD" --authenticationDatabase admin > mongo.archive.gz
mongorestore --archive=mongo.archive.gz --gzip --drop --uri "<MongoDB MONGO_PUBLIC_URL>"

# MinIO files (uploads, reports)
mc alias set local  http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
mc alias set railway https://<minio public domain> <railway MINIO_ROOT_USER> <railway MINIO_ROOT_PASSWORD>
mc mirror --preserve local/hd-files   railway/hd-files
mc mirror --preserve local/hd-reports railway/hd-reports
```

Container names follow compose project `healthdoc`. Check them with
`docker ps` first. Use a `pg_restore` of the same major version (16), or run it
from `docker run --rm postgres:16-alpine`. Keep the dump files private and
delete them once step 7 passes. They contain the whole database.

Check the counts match before going on. For example, compare
`SELECT count(*) FROM patients` and `SELECT version_num FROM alembic_version`
on both sides.

Turn the TCP proxies off when done.

### 5. Copy the staff logins

Deploy `keycloak` now (it needs only `KeycloakDB`). The PC's Keycloak runs in `start-dev`, so its users are stored in an embedded
H2 file inside the container, not in a database you can dump. On Railway,
`keycloak` starts with the hardened realm baked into its image (TOTP forced,
strong password policy, redirects only to `https://$PUBLIC_HOST`). Users are
then copied across with
[`scripts/copy_keycloak_users.py`](scripts/copy_keycloak_users.py), which:

- reads users and their realm roles from the PC through the admin API
  (read-only, while the server keeps running);
- keeps each user's **Keycloak id**. HealthDoc's `users.keycloak_sub` is that
  id, so the restored Postgres rows still match. New ids would make every
  signed-in call return 401;
- does **not** copy `devpass`. Each user gets a random temporary password and
  must set a new one and enrol TOTP at first sign-in.

```bash
export KEYCLOAK_ADMIN_PASSWORD='<the PC keycloak admin password, from .env>'
python3 deploy/railway/scripts/copy_keycloak_users.py export \
  --source http://127.0.0.1:8081/auth --out kc-users.json --passwords-out kc-temp-passwords.txt

# The admin API is not on the public address (W1). Give the keycloak service a
# temporary Railway domain (Settings -> Networking, port 8080), import, then
# delete that domain.
export KEYCLOAK_ADMIN_PASSWORD='<the Railway keycloak admin password>'
python3 deploy/railway/scripts/copy_keycloak_users.py import \
  --target https://<temporary keycloak domain>/auth --file kc-users.json
```

The import checks that every user exists on Railway with its original id, and
exits non-zero if any is missing. Running it again is safe: existing users are
skipped. Hand out the temporary passwords from `kc-temp-passwords.txt`
privately, then delete both files.

### 6. Deploy and check

Deploy in this order: `minio` → `keycloak` (already up from step 5) → `backend` (runs migrations) →
`monitor-capture` → `frontend` → `edge`. Then:

- `https://app.healthdoc.world/api/v1/health` → `{"status":"ok",…}`
- `/api/v1/health/deep` reports Postgres OK
- `https://app.healthdoc.world/auth/admin/` → 404 (W1)
- sign in as one role, open a patient, download a stored file (MinIO link)

### 7. Move ABDM callbacks (needs owner approval at the time)

NHA's bridge points at `https://abdm.healthdoc.world`, which today is a
Cloudflare tunnel to the Mac. To move it, add `abdm.healthdoc.world` as a
second custom domain on `edge`, then change that DNS record in Cloudflare from
the tunnel to the CNAME Railway shows. Set Cloudflare SSL to **Full** if the
record is proxied. The bridge URL at NHA stays the same, so there is no
re-registration. Check that a callback GET still returns 405, as it did
locally.

After that, deploy `abdm-runner-dev001` and `abdm-runner-dev002`. **Never run
the runners on the Mac and on Railway at the same time.** They would claim
the same jobs. Both use the `--created-since` values from the work summary.

### 8. Desktop app

`frontend/electron/main.ts` is a thin window that loads `HEALTHDOC_URL`. Point
it at the hosted address:

```bash
cd frontend && HEALTHDOC_URL=https://app.healthdoc.world npm run electron:dev
```

The backend already allows the `app://healthdoc` origin. Building a signed
installer (electron-builder) is a separate follow-up.

## Rollback

Until step 7, the Mac is untouched: `docker start healthdoc-backend-1
healthdoc-frontend-1 healthdoc-nginx-1` puts it back. After step 7, switch the `abdm` DNS record back
to the tunnel, stop the Railway runners, and restart the Mac runners.

## Cost

Railway bills by the minute for what each service actually uses
([pricing](https://docs.railway.com/pricing/plans)): RAM US$10 per GB-month,
CPU US$20 per vCPU-month, volumes US$0.15 per GB-month, egress US$0.05 per
GB. Builds are free. Pro's US$20 fee **is** US$20 of usage credit, so the
bill is the larger of US$20 and the usage.

Estimate for test and demo use (light traffic). These are expected steady
memory figures, not measurements:

| Service | RAM | RAM cost |
|---|---|---|
| keycloak (JVM) | ~0.8 GB | $8 |
| backend | ~0.4 GB | $4 |
| frontend (Next.js) | ~0.3 GB | $3 |
| Postgres | ~0.3 GB | $3 |
| MongoDB | ~0.3 GB | $3 |
| minio | ~0.2 GB | $2 |
| monitor-capture | ~0.2 GB | $2 |
| abdm-runner ×2 | ~0.2 GB each | $4 |
| KeycloakDB | ~0.15 GB | $1.5 |
| Redis, edge | <0.1 GB | $1 |
| **RAM total** | **~3.1 GB** | **~$31** |

Add about $10 of CPU (roughly 0.5 vCPU used on average across all services
when idle or lightly used), about $1.50 for ~10 GB of volumes, and under $1
of egress. That is **about US$40–45 a month in total**, and the US$20 fee is
part of it, not added on top. Heavier use (many testers, large uploads, load
tests) pushes the CPU and egress lines up, to roughly US$60–80.

To keep it down, don't deploy the two ABDM runners until they're needed (−$4),
and set a usage limit under Workspace → Usage so a mistake cannot run up a
bill. Check the usage page after the first week and replace these guesses with
real figures.
