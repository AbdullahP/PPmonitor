.PHONY: dev dev-down test logs shell lint

# Start all services in dev mode (mock server, disabled Discord)
dev:
	docker-compose -f docker-compose.yml -f docker-compose.override.yml up --build

# Stop all services
down:
	docker-compose -f docker-compose.yml -f docker-compose.override.yml down

# Run tests
test:
	docker-compose -f docker-compose.yml -f docker-compose.override.yml run --rm monitor python -m pytest tests/ -v

# Follow logs
logs:
	docker-compose -f docker-compose.yml -f docker-compose.override.yml logs -f

# Shell into monitor container
shell:
	docker-compose -f docker-compose.yml -f docker-compose.override.yml exec monitor bash

# Lint
lint:
	docker-compose -f docker-compose.yml -f docker-compose.override.yml run --rm monitor python -m ruff check .

# Toggle mock product stock (for testing)
mock-stock:
	curl -s -X POST http://localhost:8099/admin/set-stock \
		-H 'Content-Type: application/json' \
		-d '{"product_id":"9300000239014079","status":"in_stock"}' | python -m json.tool

mock-oos:
	curl -s -X POST http://localhost:8099/admin/set-stock \
		-H 'Content-Type: application/json' \
		-d '{"product_id":"9300000239014079","status":"out_of_stock"}' | python -m json.tool

mock-state:
	curl -s http://localhost:8099/admin/state | python -m json.tool

# Production (no mock server, no volume mounts)
prod:
	docker-compose -f docker-compose.yml up --build -d
