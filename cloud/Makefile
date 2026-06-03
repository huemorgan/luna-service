.PHONY: up down dev test db-up db-down

db-up:
	docker compose -f ../dev/cloud/docker-compose.yml up -d
	@echo "Waiting for Postgres..."
	@until docker exec cloud-cp-postgres pg_isready -U luna -d lunaservice 2>/dev/null; do sleep 1; done
	@echo "Postgres ready."

db-down:
	docker compose -f ../dev/cloud/docker-compose.yml down

dev: db-up
	cd .. && uvicorn cloud.main:app --reload --host 0.0.0.0 --port 8100

test: db-up
	cd .. && python -m pytest cloud/tests/ -v

down: db-down
