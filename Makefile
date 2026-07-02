COMPOSE := docker compose -f docker-compose.yml

.PHONY: up down migrate test lint logs

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

migrate:
	$(COMPOSE) exec app alembic upgrade head

test:
	$(COMPOSE) exec app pytest -q

lint:
	$(COMPOSE) exec app ruff check .
	$(COMPOSE) exec app black --check .

logs:
	$(COMPOSE) logs -f app

