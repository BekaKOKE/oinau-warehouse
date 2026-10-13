# OINAU-PRO — единая точка входа в проект.
# Новый разработчик должен стартовать командой `make setup`, не читая инструкций.
#
# Все цели рассчитаны на Docker. Если Docker недоступен (или на Windows
# без него), инфраструктуру и приложения запускают вручную — пошагово
# описано в README, раздел «Запуск без Docker».

COMPOSE := docker compose -f infra/docker/compose.dev.yaml --env-file .env
INFRA := $(COMPOSE) --profile infra
BACKEND := $(COMPOSE) exec -T backend

# Production-стек. Все цели с префиксом prod- рассчитаны на VPS и читают
# .env.production, которого в репозитории нет (см. .env.production.example).
PROD := docker compose -f infra/docker/compose.prod.yaml --env-file .env.production

.DEFAULT_GOAL := help
.PHONY: help setup up up-infra down restart logs ps build rebuild clean \
        migrate makemigration downgrade seed reseed superuser api-key shell psql redis-cli \
        test test-backend test-web test-cov lint format check gen-types secrets-scan \
        install build-web \
        prod-config prod-build prod-up prod-down prod-ps prod-logs prod-migrate \
        prod-superuser prod-health prod-backup prod-restore-verify

help: ## Показать список команд
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	 | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ------------------------------------------------------------------ окружение
setup: ## Первичная настройка проекта (выполнить один раз)
	@test -f .env || (cp .env.example .env && echo "Создан .env из .env.example")
	@echo "Генерирую SECRET_KEY..."
	@command -v openssl >/dev/null && \
	  sed -i.bak "s|^SECRET_KEY=.*|SECRET_KEY=$$(openssl rand -hex 32)|" .env && rm -f .env.bak || true
	@$(MAKE) up
	@$(MAKE) migrate
	@$(MAKE) seed
	@$(MAKE) gen-types
	@echo ""
	@echo "Готово:"
	@echo "  Сайт          http://localhost:3000"
	@echo "  Админка       http://localhost:3001"
	@echo "  API           http://localhost:8000"
	@echo "  Swagger       http://localhost:8000/docs"
	@echo "  Почта         http://localhost:8025"
	@echo "  MinIO Console http://localhost:9001  (minioadmin / minioadmin)"

up: ## Поднять всё окружение
	$(COMPOSE) up -d --build
	@echo "Ожидание готовности backend..."
	@until curl -fsS http://localhost:8000/health >/dev/null 2>&1; do sleep 1; done
	@echo "Backend готов: http://localhost:8000/health"

up-infra: ## Поднять только PostgreSQL, Redis, MinIO и Mailpit
	$(INFRA) up -d
	@echo "Инфраструктура поднята. Backend и frontend запускайте на хосте (см. README)."

down: ## Остановить окружение
	$(COMPOSE) down

restart: ## Перезапустить сервис: make restart s=backend
	$(COMPOSE) restart $(s)

logs: ## Логи: make logs s=backend
	$(COMPOSE) logs -f --tail=200 $(s)

ps: ## Состояние сервисов
	$(COMPOSE) ps

rebuild: ## Пересобрать образы без кэша
	$(COMPOSE) build --no-cache

clean: ## Удалить контейнеры и тома (данные БД будут потеряны)
	$(COMPOSE) down -v --remove-orphans

# ------------------------------------------------------------------- миграции
migrate: ## Применить миграции
	$(BACKEND) alembic upgrade head

makemigration: ## Создать миграцию: make makemigration m="add products"
	@test -n "$(m)" || (echo "Укажите m=\"описание\"" && exit 1)
	$(BACKEND) alembic revision --autogenerate -m "$(m)"

downgrade: ## Откатить одну миграцию
	$(BACKEND) alembic downgrade -1

seed: ## Загрузить демонстрационные данные (только для разработки)
	$(BACKEND) python -m app.scripts.seed

reseed: ## Пересоздать демонстрационные данные
	$(BACKEND) python -m app.scripts.seed --reset

superuser: ## Создать администратора
	$(COMPOSE) exec backend python -m app.scripts.create_superuser

api-key: ## Выдать ключ интеграции внешней системе (1С)
	$(COMPOSE) exec backend python -m app.scripts.create_api_key

# ---------------------------------------------------------------------- отладка
shell: ## Python-shell внутри backend
	$(COMPOSE) exec backend python

psql: ## psql к базе проекта
	$(COMPOSE) exec postgres psql -U $${POSTGRES_USER:-oinau} -d $${POSTGRES_DB:-oinau}

redis-cli: ## redis-cli
	$(COMPOSE) exec redis redis-cli

# ----------------------------------------------------------------- зависимости
install: ## Установить зависимости frontend
	pnpm install

build-web: ## Production-сборка витрины
	pnpm --filter @oinau/web build

# ----------------------------------------------------------------- качество кода
test: test-backend test-web ## Все тесты

test-backend: ## Тесты backend
	$(BACKEND) pytest

test-web: ## Тесты витрины
	pnpm --filter @oinau/web test

test-cov: ## Тесты backend с покрытием
	$(BACKEND) pytest --cov --cov-report=term-missing

lint: ## Линтеры и типы (backend + frontend)
	$(BACKEND) ruff check app tests
	$(BACKEND) ruff format --check app tests
	$(BACKEND) mypy app
	pnpm -r typecheck
	pnpm --filter @oinau/web lint
	pnpm run format:check

format: ## Автоформатирование
	$(BACKEND) ruff check --fix app tests
	$(BACKEND) ruff format app tests
	pnpm run format

check: lint test ## Полная проверка перед коммитом

secrets-scan: ## Поиск секретов в истории Git
	docker run --rm -v "$$(pwd):/repo" zricethezav/gitleaks:latest detect --source=/repo --no-git -v

# -------------------------------------------------------------------- codegen
gen-types: ## OpenAPI -> TypeScript-типы (сервер запускать не нужно)
	$(BACKEND) python -m app.scripts.dump_openapi ../../packages/api-types/openapi.json
	cd packages/api-types && pnpm exec openapi-typescript openapi.json -o src/schema.d.ts
	@rm -f packages/api-types/openapi.json
	@echo "Типы обновлены: packages/api-types/src/schema.d.ts — закоммитьте файл"

# ---------------------------------------------------------------- production
# Полная процедура деплоя описана в docs/deployment.md. Здесь только
# сокращения для повседневных операций на сервере.

prod-config: ## Проверить production-конфигурацию (ничего не запускает)
	$(PROD) config --quiet && echo "compose.prod.yaml корректен"

prod-build: ## Собрать production-образы
	$(PROD) build

prod-up: ## Запустить production-стек
	$(PROD) up -d

prod-down: ## Остановить production-стек (данные в томах остаются)
	$(PROD) down

prod-ps: ## Состояние production-сервисов
	$(PROD) ps

prod-logs: ## Логи production: make prod-logs s=backend
	$(PROD) logs -f --tail=200 $(s)

prod-migrate: ## Применить миграции в production (СНАЧАЛА make prod-backup)
	$(PROD) --profile tasks run --rm migrate

prod-superuser: ## Создать первого администратора в production
	$(PROD) exec backend python -m app.scripts.create_superuser

prod-health: ## Проверка готовности: БД, Redis, объектное хранилище
	$(PROD) exec -T backend python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready').read().decode())"

prod-backup: ## Снять резервную копию БД сейчас
	./infra/backup/pg-backup.sh

prod-restore-verify: ## Проверить восстановимость копии: make prod-restore-verify f=/path/to.dump
	@test -n "$(f)" || (echo "Укажите f=/путь/к/дампу" && exit 1)
	./infra/backup/pg-restore-verify.sh "$(f)"
