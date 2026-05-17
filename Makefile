.PHONY: up down seed test lint format format-check install pre-commit help

# ============================================================
# Sovereign Fraud Immunity Lab — Makefile
# ============================================================

## up: Start the full local dev stack
up:
	docker compose up -d --build
	@echo ""
	@echo "Stack running:"
	@echo "  Kafka:          localhost:9092"
	@echo "  Schema Registry: localhost:8081"
	@echo "  Airflow:        http://localhost:8080  (admin / admin)"
	@echo "  Neo4j Browser:  http://localhost:7474"
	@echo "  FastAPI:        http://localhost:8000/docs"
	@echo "  Dashboard:      http://localhost:3000"
	@echo ""
	@echo "Run 'make seed' to initialize topics, indexes, and graph constraints."

## down: Stop and remove all containers
down:
	docker compose down

## down-v: Stop containers and remove volumes (destructive — clears all data)
down-v:
	docker compose down -v

## seed: Initialize Kafka topics, Neo4j constraints, Pinecone indexes
seed:
	docker compose --profile seed run --rm seed
	@echo "Seed complete."

## logs: Tail logs from all services
logs:
	docker compose logs -f

## logs-api: Tail FastAPI logs
logs-api:
	docker compose logs -f api

## install: Install Python dependencies + pre-commit hooks
install:
	pip install -r requirements.txt
	pre-commit install
	@echo "Python dependencies installed and pre-commit hooks registered."

## install-dashboard: Install Next.js dashboard dependencies
install-dashboard:
	cd dashboard && npm ci

## test: Run all unit tests
test:
	pytest tests/unit -v --cov=api --cov=ml --cov=ingestion --cov=red_team \
	  --cov-report=term-missing --cov-report=xml

## test-integration: Run integration tests (requires live services)
test-integration:
	pytest tests/integration -v -m integration

## test-red-team: Run red-team validation tests
test-red-team:
	pytest tests/red_team -v -m red_team

## lint: Run Ruff linter on all Python files
lint:
	ruff check .
	cd dashboard && npx eslint . --ext .ts,.tsx --max-warnings 0

## format: Auto-format Python (Black) and TypeScript (Prettier)
format:
	black .
	cd dashboard && npx prettier --write .

## format-check: Check formatting without modifying files (used in CI)
format-check:
	black --check .
	cd dashboard && npx prettier --check .

## pre-commit: Run all pre-commit hooks against staged files
pre-commit:
	pre-commit run --all-files

## shell-api: Open a shell in the running API container
shell-api:
	docker compose exec api bash

## shell-kafka: Open a Kafka CLI shell
shell-kafka:
	docker compose exec kafka bash

## neo4j-shell: Open Neo4j Cypher shell
neo4j-shell:
	docker compose exec neo4j cypher-shell -u neo4j -p neo4j_local_dev

## help: Show this help
help:
	@grep -E '^## ' Makefile | sed 's/## //'
