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
	@cd backend && TEST_DATABASE_URL="$(TEST_DATABASE_URL)" \
		DATABASE_URL="$(TEST_DATABASE_URL)" alembic upgrade head
	@echo "$(TEST_DB) ready at localhost:$(POSTGRES_PORT)"

test-pg: test-db  ## Run the tests that need real PostgreSQL: make test-pg k=late_utc
	@cd backend && TEST_DATABASE_URL="$(TEST_DATABASE_URL)" \
		DATABASE_URL="$(TEST_DATABASE_URL)" \
		pytest $(if $(k),-k "$(k)",) $(if $(p),$(p),tests/) -q

lint:             ## Lint backend + frontend
	$(COMPOSE) exec backend ruff check .
	$(COMPOSE) exec frontend npm run lint

certs:
	./infra/nginx/generate-dev-certs.sh
