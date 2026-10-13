# OINAU-PRO

B2B-каталог комплектующих для детских и спортивных площадок.
Домен: **oinau-pro.kz**

> **Текущий статус: этап 10 — подготовка к production.**
> Реализовано: backend (авторизация и RBAC, каталог, характеристики,
> цены, остатки, заявки, медиатека, CMS, Excel-импорт/экспорт, аудит),
> публичная витрина, кабинет B2B-клиента, админ-панель, уведомления
> и основа обмена с 1С. Репозиторий готов к развёртыванию: собраны
> production-образы, обратный прокси, резервное копирование и регламенты.
> План: [`docs/architecture.md`](docs/architecture.md).
> Структура БД: [`docs/database.md`](docs/database.md).
> Уведомления и обмен с 1С: [`docs/integrations.md`](docs/integrations.md).
> **Развёртывание: [`docs/deployment.md`](docs/deployment.md).**
> **Эксплуатация и разбор сбоев: [`docs/operations.md`](docs/operations.md).**

---

## Быстрый старт с Docker

Требуется: Docker + Docker Compose, Node 22 и pnpm 9, GNU Make.

```bash
git clone <repo> oinau-pro && cd oinau-pro
cp .env.example .env
make setup
```

`make setup` сгенерирует `SECRET_KEY`, поднимет окружение, применит
миграции, загрузит демо-данные и сгенерирует TypeScript-типы из OpenAPI.

Открыть: **<http://localhost:3000>**

| Сервис           | Адрес                                | Примечание                    |
| ---------------- | ------------------------------------ | ----------------------------- |
| Публичный сайт   | <http://localhost:3000>              |                               |
| Админка (каркас) | <http://localhost:3001>              | интерфейс — следующий этап    |
| API              | <http://localhost:8000>              |                               |
| Swagger          | <http://localhost:8000/docs>         | отключается в production      |
| Liveness         | <http://localhost:8000/health>       | процесс жив                   |
| Readiness        | <http://localhost:8000/health/ready> | PostgreSQL + Redis + MinIO    |
| Почта (Mailpit)  | <http://localhost:8025>              | перехватывает всю почту       |
| MinIO Console    | <http://localhost:9001>              | `minioadmin` / `minioadmin`   |
| PostgreSQL       | `localhost:5432`                     | `oinau` / `oinau`, БД `oinau` |
| Redis            | `localhost:6379`                     |                               |
| MinIO (S3 API)   | `localhost:9000`                     | бакет `oinau-media`           |

Список команд: `make help`

---

## Запуск без Docker

Если Docker не установлен, инфраструктуру поднимают отдельно, а backend
и frontend запускают прямо на машине. Нужны PostgreSQL 16, Redis 7,
MinIO, Python 3.12+ и Node 22 с pnpm 9.

Инфраструктуру можно поднять частично через Docker:
`make up-infra` (только PostgreSQL, Redis, MinIO, Mailpit).

### 1. Подготовить `.env`

```bash
cp .env.example .env
```

Заменить адреса на локальные — контейнерных имён на хосте нет:

```dotenv
POSTGRES_HOST=localhost
REDIS_HOST=localhost
S3_ENDPOINT_URL=http://localhost:9000
API_INTERNAL_URL=http://localhost:8000
SECRET_KEY=<openssl rand -hex 32>
```

### 2. Создать базу и включить расширения

```bash
createdb -U oinau oinau
psql -U oinau -d oinau -f infra/docker/postgres/init.sql
```

`init.sql` подключает `pg_trgm`, `unaccent`, `btree_gist`, `citext`
и `pgcrypto` — без них не применятся миграции.

### 3. Установить зависимости

```bash
# backend
cd apps/backend
python -m venv .venv
.venv/Scripts/activate        # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
cd ../..

# frontend
pnpm install
```

### 4. Применить миграции

```bash
cd apps/backend && .venv/Scripts/python -m alembic upgrade head && cd ../..
```

### 5. Загрузить демонстрационные данные

```bash
cd apps/backend && .venv/Scripts/python -m app.scripts.seed && cd ../..
```

Скрипт добавляет 9 категорий, 20 товаров со всеми типами цен, остатки,
характеристики и разделы CMS. Если MinIO недоступен, изображения
пропускаются с предупреждением, а каталог показывает заглушки —
`--no-images` отключает их явно.

### 6. Создать администратора (по необходимости)

```bash
cd apps/backend && .venv/Scripts/python -m app.scripts.create_superuser && cd ../..
```

### 7. Запустить backend

```bash
cd apps/backend && .venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

### 8. Запустить worker

Нужен, только когда изображения загружают через админку: он строит
варианты картинок. Витрине и заявкам он не требуется.

```bash
cd apps/backend && .venv/Scripts/python -m arq app.workers.main.WorkerSettings
```

### 9. Обновить типы API (только после правок схем)

`packages/api-types/src/schema.d.ts` генерируется из OpenAPI, но
**хранится в Git**: без него не собираются ни витрина, ни админка,
ни их production-образы, а образ собирается из чистого клона. После
любой правки схем Pydantic файл нужно перегенерировать и закоммитить —
CI сверяет его с кодом backend и останавливается на расхождении.

```bash
make gen-types
```

Без `make` и без запущенного сервера:

```bash
cd apps/backend
python -m app.scripts.dump_openapi ../../packages/api-types/openapi.json
cd ../../packages/api-types
pnpm exec openapi-typescript openapi.json -o src/schema.d.ts
rm openapi.json
```

### 10. Запустить витрину

```bash
pnpm --filter @oinau/web dev
```

Открыть **<http://localhost:3000>**.

> Redis нужен только ограничению частоты обращений. Если он не запущен,
> сайт продолжает работать: проверка пропускается, а в лог backend
> пишется предупреждение. `/health/ready` при этом покажет `degraded`.

---

## Публичные страницы

| Маршрут                       | Содержимое                                                                           | API                                          |
| ----------------------------- | ------------------------------------------------------------------------------------ | -------------------------------------------- |
| `/`                           | Главная: фотография площадки с интерактивными точками, категории, популярные позиции | `content/home`, `categories`, `products`     |
| `/catalog`                    | Каталог: поиск, фильтры, сортировка, постраничная навигация                          | `products`, `categories`                     |
| `/catalog/[category]`         | Раздел каталога                                                                      | `categories/{slug}`, `products`              |
| `/product/[slug]`             | Карточка: галерея, цена, ступени, характеристики, похожие                            | `products/{slug}`, `products/{slug}/related` |
| `/contacts`                   | Контакты и реквизиты                                                                 | `content/contacts`                           |
| `/delivery`                   | Доставка и оплата                                                                    | `content/delivery`                           |
| `/faq`                        | Частые вопросы                                                                       | `content/faq`                                |
| `/favorites`                  | Избранное (хранится в браузере)                                                      | —                                            |
| `/cabinet/login`              | Заглушка личного кабинета                                                            | —                                            |
| `/sitemap.xml`, `/robots.txt` | Карта сайта и правила обхода                                                         | `categories`, `products`                     |

Заявка отправляется в `POST /api/v1/public/requests`; список регионов
для формы — `GET /api/v1/public/regions`.

---

## Структура

```
apps/backend     FastAPI + SQLAlchemy 2 + Alembic — вся бизнес-логика
apps/web         Next.js — публичная витрина
apps/admin       Next.js — админ-панель (отдельное приложение)
packages/        общие TS-пакеты: типы API, HTTP-клиент, конфиги
infra/docker     Compose-окружение, init-скрипты Postgres и MinIO
docs/            архитектура, структура БД, контракты API и ADR
```

Витрина разложена так:

```
apps/web/src/app          маршруты (серверные компоненты)
apps/web/src/components   Header, Hero, PlaygroundHotspots, ProductCard,
                          CatalogFilters, RequestDrawer, ui/*
apps/web/src/lib          API-клиент, форматирование цен, разбор URL каталога
apps/web/tests            тесты (Vitest + Testing Library)
```

Почему backend, web и admin разделены — раздел 3 в `docs/architecture.md`.

---

## Ключевые правила проекта

Нарушение любого из них — блокирующее замечание на код-ревью.

1. **Секреты не попадают в Git.** Только `.env` (в `.gitignore`) и `.env.example` без значений.
   В браузер уходят лишь переменные `NEXT_PUBLIC_*`.
2. **Изображения не хранятся в репозитории и не отдаются backend'ом.** Только Object Storage (R2 локально — MinIO). В PostgreSQL — только `storage_key`.
3. **Ничего необратимого в HTTP-обработчике.** Отправка писем, Telegram, обработка картинок, импорт — только через очередь.
4. **Бизнес-логика живёт в backend.** Ни `web`, ни `admin` не считают цены и не определяют статус наличия.
5. **Деньги — `NUMERIC`, количество — `NUMERIC`, время — `TIMESTAMPTZ`.** Наружу они уходят строками; фронтенд не приводит их к `number` для арифметики.
6. **Никаких жёстких `DELETE`** для товаров, категорий, заявок и пользователей.
7. **Типы TS генерируются из OpenAPI** (`make gen-types`), руками не пишутся.
8. **Миграции не запускаются автоматически при старте контейнера** — это отдельный шаг деплоя.
9. **Состояние каталога живёт в URL.** Фильтры, поиск, сортировка и страница отражаются в строке запроса: выдачу должно быть можно переслать ссылкой.

---

## Разработка

```bash
make up                          # поднять окружение
make up-infra                    # только PostgreSQL/Redis/MinIO/Mailpit
make logs s=backend              # логи сервиса
make migrate                     # применить миграции
make makemigration m="add products"
make seed                        # демо-данные
make reseed                      # пересоздать демо-данные
make test                        # тесты backend + витрины
make lint                        # ruff + mypy + tsc + eslint + prettier
make check                       # всё перед коммитом
make superuser                   # создать первого администратора
make gen-types                   # OpenAPI -> TypeScript
make secrets-scan                # поиск утёкших секретов
make down                        # остановить
```

Без Docker те же проверки запускаются напрямую:

```bash
cd apps/backend && .venv/Scripts/python -m pytest
cd apps/backend && .venv/Scripts/python -m ruff check app tests
cd apps/backend && .venv/Scripts/python -m mypy app
pnpm --filter @oinau/web test
pnpm --filter @oinau/web typecheck
pnpm --filter @oinau/web lint
pnpm --filter @oinau/web build
```

Рекомендуется установить хуки: `pip install pre-commit && pre-commit install`.

---

## Ручная проверка витрины (smoke)

Автоматического браузерного E2E в проекте пока нет. После запуска
пройдите сценарий вручную — он занимает пару минут:

1. Открыть <http://localhost:3000> — видна фотография площадки с точками.
2. Нажать точку (например, «Канатная сеть») — открывается раздел каталога.
3. В каталоге задать поиск «канат», наличие «В наличии», сортировку по цене —
   параметры видны в адресной строке, выдача меняется.
4. Открыть кнопкой «назад» предыдущую выдачу — фильтры сохранились.
5. Открыть карточку товара — видны артикул, наличие, цена, таблица ступеней,
   характеристики и похожие позиции.
6. Указать количество и нажать «Добавить в заявку» — открывается панель заявки.
7. Изменить количество в панели, нажать «Отправить заявку» без контактов —
   поля подсвечены ошибками.
8. Заполнить имя, телефон и регион, отправить — появляется номер вида
   `R-2026-000001`.
9. Проверить заявку в админке или в базе:
   `make psql` → `select number, customer_name from requests order by id desc limit 1;`
10. Уменьшить ширину окна до ~390 px — шапка сворачивается в меню, точки
    на фотографии превращаются в прокручиваемый ряд, каталог перестраивается
    в одну колонку.

Письмо о заявке ловит Mailpit: <http://localhost:8025>.

---

## Архитектура API

Три изолированные поверхности с разной аутентификацией, CORS и rate limit:

| Префикс               | Аутентификация          | Назначение                                                                 |
| --------------------- | ----------------------- | -------------------------------------------------------------------------- |
| `/api/v1/public`      | нет                     | Витрина, каталог ([контракт](docs/api-public-catalog.md)), создание заявок |
| `/api/v1/admin`       | JWT + RBAC              | Админ-панель                                                               |
| `/api/v1/customer`    | JWT клиента             | Кабинет B2B-клиента                                                        |
| `/api/v1/integration` | API-ключ + IP allowlist | Внешние системы, 1С ([контракт и статус](docs/integrations.md))            |

---

## Production

Полный регламент — [`docs/deployment.md`](docs/deployment.md).
Короткая версия того, чем production отличается от локального запуска:

|                | Локально                           | Production                                             |
| -------------- | ---------------------------------- | ------------------------------------------------------ |
| Compose        | `infra/docker/compose.dev.yaml`    | `infra/docker/compose.prod.yaml`                       |
| Окружение      | `.env`                             | `.env.production` (шаблон — `.env.production.example`) |
| Адреса         | три порта на localhost             | один домен: `/`, `/admin`, `/api`                      |
| Хранилище      | MinIO                              | Cloudflare R2                                          |
| Почта          | Mailpit                            | настоящий SMTP                                         |
| Открыто наружу | 3000, 3001, 8000, 5432, 6379, 9000 | только 80 и 443                                        |

```bash
make prod-config     # проверить конфигурацию, ничего не запуская
make prod-build      # собрать образы
make prod-up         # запустить
make prod-migrate    # применить миграции (после make prod-backup)
make prod-health     # готовность: БД, Redis, объектное хранилище
```

Разбор сбоев и что смотреть, когда что-то не работает —
[`docs/operations.md`](docs/operations.md).

---

## Дорожная карта

Выполнены: этапы 1–5E (backend), 6 (витрина), 7 (кабинет клиента),
8 (админ-панель), 9 (уведомления и основа обмена с 1С),
10 (подготовка production-развёртывания).

Обмен с 1С реализован, но **выключен по умолчанию**: боевой обмен
включается только после сверки контракта с выгрузкой конкретной
конфигурации 1С — см. [`docs/integrations.md`](docs/integrations.md).

Полный список: раздел 15 в `docs/architecture.md`.
