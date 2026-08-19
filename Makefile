# HealthDoc dev commands — run from repo root
COMPOSE := docker compose -f infra/docker-compose.yml --env-file .env

.PHONY: setup up down logs ps migrate revision test test-db test-pg lint fe be certs

# Tests that need a real PostgreSQL read TEST_DATABASE_URL and are skipped
# without it. Built from .env so it follows POSTGRES_PORT (55432 here, not the
# 5432 CI uses) instead of hardcoding a port that is wrong on this machine.
-include .env
export
TEST_DB := $(POSTGRES_DB)_test
TEST_DATABASE_URL := postgresql+asyncpg://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@localhost:$(POSTGRES_PORT)/$(TEST_DB)

# The app's lifespan validates these before serving traffic, so any test that
# enters TestClient as a context manager errors at setup without them. Same
# values as .github/workflows/ci.yml on purpose — a test that passes locally
# and fails in CI over key config wastes more time than it saves.
#
# Deterministic test values, not secrets. Real deployments get real keys.
TEST_PII_ENCRYPTION_KEY := dkWUFyQpoVWEpmm4NovS1ketf25uP0WKr6z/sNC1ADk=
TEST_AADHAAR_HMAC_KEY   := MYXTZ1OUDwLh3yYU63CgWnvqVib9FJHqEdLoi4IUrAA=
# .env points REDIS_URL and MINIO_ENDPOINT at the compose service names, which
# is correct for the backend container and unresolvable from the host. Tests run
# on the host, so they need the published ports instead.
TEST_REDIS_URL      := redis://localhost:$(or $(REDIS_PORT),6379)/0
TEST_MINIO_ENDPOINT := localhost:$(or $(MINIO_PORT),9000)

TEST_ENV := TEST_DATABASE_URL="$(TEST_DATABASE_URL)" DATABASE_URL="$(TEST_DATABASE_URL)" \
	PII_ENCRYPTION_KEY="$(TEST_PII_ENCRYPTION_KEY)" \
	AADHAAR_HMAC_KEY="$(TEST_AADHAAR_HMAC_KEY)" \
	REDIS_URL="$(TEST_REDIS_URL)" \
	MINIO_ENDPOINT="$(TEST_MINIO_ENDPOINT)"

setup:            ## First-time setup: .env, certs, build, start, migrate
	./scripts/dev_setup.sh

up:               ## Start the full stack
	$(COMPOSE) up -d

down:             ## Stop the stack (data volumes kept)
	$(COMPOSE) down

logs:             ## Tail all logs
	$(COMPOSE) logs -f --tail=100

ps:
	$(COMPOSE) ps

migrate:          ## Apply DB migrations
	$(COMPOSE) exec backend alembic upgrade head

revision:         ## New migration: make revision m="add foo table"
	$(COMPOSE) exec backend alembic revision --autogenerate -m "$(m)"

test:             ## Backend tests
	$(COMPOSE) exec backend pytest -q

test-db:          ## Create + migrate the test database (idempotent)
	@$(COMPOSE) exec -T postgres psql -U $(POSTGRES_USER) -d postgres -tc \
		"SELECT 1 FROM pg_database WHERE datname='$(TEST_DB)'" | grep -q 1 \
		|| $(COMPOSE) exec -T postgres createdb -U $(POSTGRES_USER) $(TEST_DB)
	@cd backend && $(TEST_ENV) alembic upgrade head
	@echo "$(TEST_DB) ready at localhost:$(POSTGRES_PORT)"

test-db-reset:    ## Drop and rebuild the test database (after editing a migration)
	-@$(COMPOSE) exec -T postgres dropdb -U $(POSTGRES_USER) --if-exists $(TEST_DB)
	@$(MAKE) test-db

test-pg: test-db  ## Run the tests that need real PostgreSQL: make test-pg k=late_utc
	@cd backend && $(TEST_ENV) pytest $(if $(k),-k "$(k)",) $(if $(p),$(p),tests/) -q

lint:             ## Lint backend + frontend
	$(COMPOSE) exec backend ruff check .
	$(COMPOSE) exec frontend npm run lint

certs:
	./infra/nginx/generate-dev-certs.sh
