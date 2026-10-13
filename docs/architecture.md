# OINAU-PRO — Архитектурный документ (Этап 1)

**Домен:** oinau-pro.kz
**Статус:** проектирование. Код не пишется.
**Версия:** 1.0

---

## 0. Резюме решений

| Область         | Решение                                                                                          |
| --------------- | ------------------------------------------------------------------------------------------------ |
| Репозиторий     | Monorepo: `apps/backend` (FastAPI), `apps/web` (Next.js), `apps/admin` (Next.js), `packages/*`   |
| БД              | PostgreSQL 16, одна база, миграции Alembic                                                       |
| Цены            | Отдельная таблица ценовых уровней + прайс-листы. Цена никогда не поле в `products`               |
| Остатки         | Отдельная таблица `stocks` по складам. Публичный статус — вычисляемый                            |
| Характеристики  | Гибрид: нормализованный справочник атрибутов (фильтруемые) + JSONB (описательные)                |
| Изображения     | Cloudflare R2 + CDN на `cdn.oinau-pro.kz`. В PostgreSQL только `storage_key`                     |
| Загрузка файлов | Presigned URL, файл не проходит через FastAPI                                                    |
| Заявки          | Единая таблица `requests` с полем `kind`, позиции — снапшот товара                               |
| Уведомления     | Transactional Outbox + фоновый воркер. Не в HTTP-запросе                                         |
| 1С              | Не реализуется. Закладываются `external_id`, `sku`, отдельный `/api/v1/integration`, pull-модель |
| Фон/очереди     | Redis + ARQ (или Celery)                                                                         |
| Инфраструктура  | Docker Compose локально, тот же образ в проде                                                    |

---

## 1. Общая архитектура

### 1.1 Логическая схема

```
                    ┌───────────────────────────┐
   Браузер ────────►│  cdn.oinau-pro.kz         │  изображения (R2 + CDN)
   (картинки)       │  Cloudflare R2 public     │  backend не участвует
                    └───────────────────────────┘

                    ┌───────────────────────────┐
   Браузер ────────►│  oinau-pro.kz             │  Next.js (SSR/ISR)
   (страницы)       │  apps/web                 │
                    └─────────────┬─────────────┘
                                  │ REST /api/v1/public
                    ┌─────────────▼─────────────┐
   Менеджер ───────►│  api.oinau-pro.kz         │  FastAPI
                    │  apps/backend             │
   admin.oinau-pro  │  /public /admin /integration
        │           └──┬────────┬───────────┬───┘
        │              │        │           │
        │        ┌─────▼──┐ ┌───▼───┐  ┌────▼────┐
        └───────►│Postgres│ │ Redis │  │   R2    │
                 └────────┘ └───┬───┘  │(presign)│
                                │      └─────────┘
                          ┌─────▼──────┐
                          │  Worker    │ ► Telegram
                          │  (ARQ)     │ ► SMTP
                          └────────────┘   ► обработка изображений
```

### 1.2 Компоненты

| Компонент  | Роль                                          | Публичный доступ                     |
| ---------- | --------------------------------------------- | ------------------------------------ |
| `web`      | Публичный сайт, каталог, корзина-заявка, SEO  | Да, `oinau-pro.kz`                   |
| `admin`    | Админ-панель, SPA                             | Да, но `admin.oinau-pro.kz` + защита |
| `backend`  | Единственный источник бизнес-логики, REST API | `api.oinau-pro.kz`                   |
| `worker`   | Уведомления, обработка изображений, импорты   | Нет                                  |
| `postgres` | Все структурированные данные                  | Нет                                  |
| `redis`    | Очереди задач, rate limiting, кэш             | Нет                                  |
| `R2 + CDN` | Бинарные файлы                                | Да, `cdn.oinau-pro.kz`               |

### 1.3 Ключевые архитектурные принципы

1. **Backend — единственный владелец бизнес-логики.** Ни `web`, ни `admin` не содержат правил расчёта цены, статуса наличия или валидации заявки. Иначе логика разъедется между тремя кодовыми базами.
2. **Backend не раздаёт бинарные файлы.** Ни в одном сценарии, кроме генерации presigned URL и отдачи экспортных Excel-файлов.
3. **Ничего необратимого в HTTP-обработчике.** Отправка Telegram/Email, ресайз картинок, разбор Excel — только через очередь.
   _Уточнение этапа 5E:_ Excel-импорт каталога выполняется синхронно — для каталога в сотни–тысячи позиций это доли секунды, а фоновая система задач ради него не оправдана. Разбор идёт в пуле потоков, с лимитами размера и строк; применение — одной транзакцией (откатывается целиком). Перенос подтверждения в воркер не меняет контракт: см. `docs/api-catalog-import-export.md`.
4. **Три поверхности API физически разделены** по префиксу, аутентификации, rate limit и CORS: `public`, `admin`, `integration`.
5. **Схема данных нейтральна к источнику.** Товар одинаково создаётся из админки, Excel и (в будущем) 1С. Ни одна таблица не проектируется «под 1С» или «под Excel».

### 1.4 Спорные моменты в исходных требованиях

Разделы, где я рекомендую отойти от ТЗ или дополнить его, — отмечены ⚠️ по всему документу. Сводка:

| #   | Требование                            | Проблема                                                                                       | Рекомендация                                                                                           |
| --- | ------------------------------------- | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| ⚠️1 | «Заявки» и «Лиды» как разные сущности | Дублирование таблиц, статусов, воронки                                                         | Одна таблица `requests` с полем `kind`. В админке — два раздела-фильтра                                |
| ⚠️2 | Ресайз изображений на backend         | Работает, но требует воркера, диска, CPU                                                       | Рассмотреть Cloudflare Images / Image Transformations — ресайз на edge, без воркера                    |
| ⚠️3 | Про язык сайта ничего не сказано      | Казахстан → почти наверняка потребуется KZ-версия. Ретрофит переводов в готовую схему — дорого | Решить сейчас. Заложить структуру переводов даже если запускаемся на RU                                |
| ⚠️4 | Hoster.kz                             | Shared-хостинг не подойдёт под Docker + Postgres + Redis + воркер                              | Только VPS/Cloud, минимум 2 vCPU / 4 ГБ RAM                                                            |
| ⚠️5 | Персональные данные в заявках         | ЗРК «О персональных данных» — требования к хранению ПДн граждан РК                             | БД с ПДн — на территории РК (Hoster.kz подходит). В R2 хранить только изображения товаров, никаких ПДн |
| ⚠️6 | Отдельная админка на Next.js          | Согласен, но нужен план против дублирования кода                                               | Monorepo + общие пакеты типов и API-клиента                                                            |
| ⚠️7 | «до 100 товаров на старте»            | Соблазн упростить схему                                                                        | Схема ниже держит десятки тысяч SKU без переделки. Упрощать не надо — переделка дороже                 |

---

## 2. Структура monorepo

```
oinau-pro/
├── apps/
│   ├── backend/
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── core/                  # config, security, exceptions, logging
│   │   │   │   ├── config.py          # Pydantic Settings, чтение .env
│   │   │   │   ├── security.py        # JWT, хеширование паролей
│   │   │   │   ├── permissions.py     # RBAC-декораторы и зависимости
│   │   │   │   └── pagination.py
│   │   │   ├── db/
│   │   │   │   ├── base.py            # DeclarativeBase, naming_convention
│   │   │   │   ├── session.py         # async engine, sessionmaker
│   │   │   │   └── types.py           # общие типы (Money, slug)
│   │   │   ├── modules/               # деление по домену, не по слою
│   │   │   │   ├── catalog/           # categories, products, attributes
│   │   │   │   │   ├── models.py
│   │   │   │   │   ├── schemas.py
│   │   │   │   │   ├── service.py
│   │   │   │   │   ├── repository.py
│   │   │   │   │   └── router_public.py / router_admin.py
│   │   │   │   ├── pricing/
│   │   │   │   ├── inventory/
│   │   │   │   ├── media/
│   │   │   │   ├── requests/          # заявки и лиды
│   │   │   │   ├── content/           # страницы, баннеры, FAQ
│   │   │   │   ├── settings/
│   │   │   │   ├── users/
│   │   │   │   ├── imports/
│   │   │   │   └── integration/       # контракт для внешних систем
│   │   │   ├── api/
│   │   │   │   └── v1/
│   │   │   │       ├── public.py      # сборка публичных роутеров
│   │   │   │       ├── admin.py
│   │   │   │       └── integration.py
│   │   │   ├── workers/
│   │   │   │   ├── main.py            # ARQ worker settings
│   │   │   │   └── tasks/             # notifications, images, imports
│   │   │   └── infrastructure/
│   │   │       ├── storage/           # S3/R2 клиент, presign
│   │   │       ├── notifications/     # telegram, smtp
│   │   │       └── outbox.py
│   │   ├── alembic/
│   │   ├── tests/
│   │   ├── pyproject.toml
│   │   └── Dockerfile
│   │
│   ├── web/                           # публичный сайт (Next.js App Router)
│   │   ├── src/app/
│   │   ├── src/components/
│   │   ├── src/lib/api/               # обёртка над packages/api-client
│   │   └── Dockerfile
│   │
│   └── admin/                         # админка (Next.js, CSR)
│       ├── src/app/
│       └── Dockerfile
│
├── packages/
│   ├── api-types/                     # TS-типы, СГЕНЕРИРОВАННЫЕ из OpenAPI
│   ├── api-client/                    # типизированный fetch-клиент
│   ├── ui/                            # общие примитивы (опционально)
│   └── config/                        # eslint, tsconfig, prettier
│
├── infra/
│   ├── docker/
│   │   ├── compose.dev.yaml
│   │   ├── compose.prod.yaml
│   │   └── postgres/init.sql
│   └── nginx/ | traefik/
│
├── docs/
│   ├── architecture.md                # этот документ
│   ├── adr/                           # архитектурные решения
│   └── api.md
│
├── .env.example                       # реальный .env — только локально и в CI-секретах
├── Makefile
├── pnpm-workspace.yaml
└── README.md
```

### Комментарии

**Деление backend по доменам, а не по слоям.** Классическое `models/`, `schemas/`, `routers/` на 15+ сущностях превращается в скачки между четырьмя папками при каждом изменении. `modules/catalog/*` держит всё, что относится к каталогу, рядом.

**`packages/api-types` генерируется, а не пишется руками.** FastAPI отдаёт OpenAPI-схему → `openapi-typescript` → TS-типы. Один источник истины, никакой ручной синхронизации DTO между тремя приложениями. Генерация запускается в CI и падает, если типы разошлись.

**Python не входит в pnpm-workspace.** Backend живёт своей жизнью (uv или Poetry). Монорепо здесь — про общий Git, общий CI и общие TS-пакеты, а не про единый пакетный менеджер. Turborepo подключать не обязательно, но полезен для кэша сборок.

---

## 3. Почему backend / frontend / admin разделены

**Backend отдельно от frontend — не обсуждается.** Причина не в моде на SPA, а в том, что 1С, мобильное приложение и Excel-импорт будут работать с одним и тем же API. Если логика зашита в Next.js server actions, интеграция с 1С потребует её дублирования.

**Админка отдельным приложением — рекомендую, и вот почему:**

1. **Поверхность атаки.** Публичный сайт индексируется, ходит по нему кто угодно. Админка на отдельном origin можно закрыть по IP, поставить basic auth сверху, отключить индексацию, применить строгий CSP. Внутри одного Next.js это делается костылями через middleware.
2. **Бандл.** Админка — это WYSIWYG-редактор, таблицы, загрузчик файлов, графики. Это сотни килобайт JS, которые не должны попадать в бандл публичного каталога. Next.js делит код по маршрутам, но общие зависимости всё равно протекают в shared chunks.
3. **Разные модели рендеринга.** Публичный сайт: SSR/ISR, агрессивное кэширование, SEO, работа без JS. Админка: чистый CSR, никакого SEO, всё за авторизацией. Оптимальные конфиги для них взаимно противоречивы.
4. **Независимый деплой.** Правка стиля карточки товара не должна выкатывать админку и наоборот. Разные частоты релизов, разные риски.
5. **Разные требования к доступности.** Падение админки не должно ронять витрину, которая приносит заявки.

**Цена этого решения** — дублирование типов, клиента API, компонентов. Она полностью нейтрализуется monorepo с `packages/api-types` и `packages/api-client`. Без monorepo разделение админки я бы не рекомендовал.

**Когда разделять НЕ стоит:** если бы админкой пользовались 1–2 человека и функционал ограничивался CRUD по товарам, я бы предложил готовое решение и не писал админку вообще. Учитывая заявленный объём (каталог, заявки, лиды, контент, импорт, роли) — своя админка оправдана.

---

## 4. Архитектура PostgreSQL (высокий уровень)

### 4.1 Общие правила

- **PostgreSQL 16.** Одна база, одна схема `public` (несколько схем усложняют миграции без выигрыша на этом масштабе).
- **Первичные ключи: `BIGINT GENERATED ALWAYS AS IDENTITY`** для внутренних сущностей. Для сущностей, чей ID утекает наружу (медиафайлы, заявки, ключи объектов) — дополнительно `UUID` как публичный идентификатор. Не отдавайте наружу автоинкремент: он раскрывает объёмы бизнеса и облегчает перебор.
- **Деньги: `NUMERIC(14,2)`.** Никогда `float`/`double precision`. Валюта — отдельное поле `CHAR(3)`, по умолчанию `KZT`, даже если пока валюта одна.
- **Количество: `NUMERIC(14,3)`**, не `INTEGER`. ⚠️ 1С регулярно оперирует дробными количествами (метры каната, килограммы). Переезд с `INT` на `NUMERIC` в проде с историей — болезненный.
- **Все временные метки: `TIMESTAMPTZ`**, хранение в UTC, конвертация в `Asia/Almaty` на фронте. `TIMESTAMP` без таймзоны — источник вечных багов.
- **Мягкое удаление** (`deleted_at TIMESTAMPTZ NULL`) для товаров, категорий, пользователей, заявок. Жёсткий `DELETE` ломает исторические заявки и будущую синхронизацию с 1С. Партиальные индексы `WHERE deleted_at IS NULL`.
- **Аудит-поля везде:** `created_at`, `updated_at`, `created_by_id`, `updated_by_id`.
- **Именование:** `snake_case`, таблицы во множественном числе, FK — `<entity>_id`. Явный `naming_convention` в SQLAlchemy `MetaData`, иначе Alembic будет генерировать миграции с автогенерированными именами constraint'ов и `downgrade` перестанет работать.
- **Расширения:** `pg_trgm` (поиск с опечатками), `unaccent`, `btree_gist` (для ограничений на диапазоны цен), опционально `ltree` (дерево категорий).

### 4.2 Поиск

На горизонте нескольких тысяч товаров **Elasticsearch не нужен и будет архитектурной ошибкой** (лишний сервис, лишняя синхронизация, лишний RAM). Достаточно:

- материализованная колонка `search_vector tsvector GENERATED ALWAYS AS (...) STORED` по названию, артикулу, ключевым словам;
- `GIN`-индекс по ней;
- `pg_trgm` + `GIN` по названию и артикулу для поиска по подстроке и опечаткам;
- русская конфигурация FTS.

Порог пересмотра — примерно 50 000+ товаров или требование фасетного поиска с релевантностью. До этого Postgres справляется.

### 4.3 Индексы, которые нужны сразу

```
products:            UNIQUE(sku) WHERE deleted_at IS NULL
                     UNIQUE(slug) WHERE deleted_at IS NULL
                     UNIQUE(external_id) WHERE external_id IS NOT NULL
                     INDEX(status, is_active)
                     GIN(search_vector)
categories:          UNIQUE(slug), INDEX(parent_id), INDEX(path) [ltree/GIST]
product_categories:  PK(product_id, category_id), INDEX(category_id)
product_prices:      INDEX(product_id, price_list_id, min_qty)
                     EXCLUDE USING gist (product_id WITH =, price_list_id WITH =, qty_range WITH &&)
stocks:              UNIQUE(product_id, warehouse_id)
product_media:       INDEX(product_id, sort_order)
requests:            INDEX(status, created_at DESC), INDEX(kind), UNIQUE(idempotency_key)
product_attr_values: INDEX(attribute_id, value_option_id) -- для фасетных фильтров
                     INDEX(product_id)
```

### 4.4 Что НЕ делать

- Не хранить цену, остаток и «в наличии» полями в `products`.
- Не хранить пути к файлам в виде `/static/products/1.jpg`.
- Не использовать `ENUM`-типы PostgreSQL для статусов, которые будут расширяться (добавление значения в enum — миграция с блокировкой). Использовать `VARCHAR` + `CHECK` или справочную таблицу.
- Не делать `ON DELETE CASCADE` на связях товар → позиция заявки. Заявка должна пережить удаление товара.

---

## 5. Основные сущности и связи

### 5.1 Карта сущностей

```
                        ┌──────────────┐
                        │  categories  │◄──┐ parent_id (self-FK)
                        └──────┬───────┘   │
                               │ M:N       │
                        ┌──────▼───────────┴────┐
        ┌───────────────►      products         ◄───────────────┐
        │               └──┬─────┬─────┬─────┬──┘               │
        │                  │     │     │     │                  │
   ┌────┴─────┐   ┌────────▼┐ ┌──▼───┐ │ ┌───▼──────────┐  ┌────┴──────┐
   │price_list│◄──┤ product │ │stocks│ │ │product_media │  │ product_  │
   └──────────┘   │ _prices │ └──┬───┘ │ └──────┬───────┘  │attr_values│
                  └─────────┘    │     │        │          └────┬──────┘
                            ┌────▼───┐ │  ┌─────▼──────┐   ┌────▼──────┐
                            │warehou-│ │  │media_files │   │attributes │
                            │  ses   │ │  └────────────┘   └────┬──────┘
                            └────────┘ │                   ┌────▼──────┐
                                       │                   │attribute_ │
                                       │                   │  options  │
                                       │                   └───────────┘
                                       │ snapshot (без FK-каскада)
                            ┌──────────▼─────┐
                            │ request_items  │
                            └────────┬───────┘
                                     │
                            ┌────────▼───────┐      ┌──────────────────┐
                            │   requests     ├─────►│ request_comments │
                            │ (kind: cart /  │      ├──────────────────┤
                            │  custom / call)│─────►│ request_status_  │
                            └────────┬───────┘      │     history      │
                                     │              └──────────────────┘
                            ┌────────▼────────────┐
                            │ notification_outbox │──► worker ──► TG/Email
                            └─────────────────────┘

  users ──► roles/permissions        settings (key-value)
  pages / banners / faq              import_jobs ──► import_job_errors
  api_keys (для 1С)                  audit_log      sync_log
```

### 5.2 Перечень таблиц

**Каталог**
`categories`, `products`, `product_categories`, `attributes`, `attribute_options`, `category_attributes`, `product_attribute_values`

**Цены**
`price_lists`, `product_prices`

**Склад**
`warehouses`, `stocks`, (в будущем) `stock_movements`

**Медиа**
`media_files`, `product_media`

**Заявки**
`requests`, `request_items`, `request_comments`, `request_status_history`

**Пользователи**
`users`, `refresh_tokens`, `api_keys`

**Контент и настройки**
`pages`, `banners`, `faqs`, `settings`, `regions`

**Служебные**
`notification_outbox`, `import_jobs`, `import_job_errors`, `sync_log`, `audit_log`

---

## 6. Хранение данных по областям

### 6.1 Категории

```
categories
  id                 BIGINT PK
  external_id        VARCHAR(64) NULL UNIQUE     -- GUID из 1С
  parent_id          BIGINT NULL FK -> categories(id)
  slug               VARCHAR(160) UNIQUE
  name               VARCHAR(255)
  description        TEXT NULL
  path               LTREE / VARCHAR             -- материализованный путь: 1.14.37
  depth              SMALLINT
  sort_order         INT DEFAULT 0
  is_active          BOOLEAN DEFAULT true
  seo_title, seo_description, seo_h1
  image_media_id     BIGINT NULL FK -> media_files(id)
  created_at, updated_at, deleted_at
```

**Adjacency list + материализованный путь.** `parent_id` даёт простую нормальную структуру, `path` даёт получение всей ветки одним запросом без рекурсии — это критично для страницы категории, где показываются товары из всех подкатегорий. Пересчёт `path` — в сервисном слое при смене родителя (операция редкая).

Nested Sets я не рекомендую: перестройка дерева при каждой вставке, высокий риск ошибок, выигрыш только на очень больших деревьях.

### 6.2 Товары

```
products
  id                 BIGINT PK
  uuid               UUID UNIQUE DEFAULT gen_random_uuid()
  external_id        VARCHAR(64) NULL UNIQUE     -- GUID номенклатуры 1С
  sku                VARCHAR(64) UNIQUE          -- артикул, бизнес-ключ
  slug               VARCHAR(200) UNIQUE
  name               VARCHAR(500)
  short_description  TEXT NULL
  description        TEXT NULL                   -- HTML из редактора, санитизировать
  brand              VARCHAR(120) NULL
  unit               VARCHAR(16) DEFAULT 'шт'    -- шт / м / кг / компл
  status             VARCHAR(24) DEFAULT 'draft' -- draft|published|archived
  price_mode         VARCHAR(16) DEFAULT 'fixed' -- fixed|from|tiered|on_request
  is_featured        BOOLEAN DEFAULT false
  min_order_qty      NUMERIC(14,3) DEFAULT 1
  weight_kg          NUMERIC(10,3) NULL
  specs              JSONB DEFAULT '{}'          -- описательные характеристики
  seo_title, seo_description
  search_vector      TSVECTOR GENERATED STORED
  sync_source        VARCHAR(16) DEFAULT 'manual'-- manual|1c|excel
  synced_at          TIMESTAMPTZ NULL
  created_at, updated_at, deleted_at
  created_by_id, updated_by_id
```

Связь с категориями — **many-to-many**:

```
product_categories
  product_id   BIGINT FK
  category_id  BIGINT FK
  is_primary   BOOLEAN DEFAULT false   -- для канонического URL и хлебных крошек
  PK (product_id, category_id)
```

Один товар часто относится к нескольким разделам («крепления» и «элементы качелей»). Жёсткая привязка `category_id` в `products` рано или поздно потребует миграции. `is_primary` решает вопрос канонического URL для SEO — частичный уникальный индекс `UNIQUE(product_id) WHERE is_primary`.

`status` вместо булева `is_published` — потому что нужны как минимум черновик, публикация и архив, и список будет расти (например, `discontinued`).

⚠️ **О языках.** Если KZ-версия сайта планируется, решение нужно принять сейчас. Два варианта:

- **JSONB-поля:** `name JSONB` вида `{"ru": "...", "kk": "..."}`. Просто, но ломает FTS-индексы и усложняет валидацию.
- **Таблицы переводов:** `product_translations(product_id, locale, name, description, seo_*)` с `PK(product_id, locale)`. Больше кода, но корректный поиск по каждому языку, нормальные индексы, легко добавить язык.

Рекомендую второй вариант, даже если запускаетесь только на RU: таблица создаётся сразу, заполняется одной локалью. Добавить казахский потом — это вставка строк, а не миграция схемы.

### 6.3 Характеристики (атрибуты)

**Гибридная модель — сознательный компромисс.**

Чистый EAV даёт фильтрацию, но каждая карточка товара — это N джойнов, а запись атрибутов превращается в мучение. Чистый JSONB даёт удобство, но фасетные фильтры («канат Ø16 мм, красный, полиамид») на JSONB работают приемлемо только с GIN-индексом и всё равно не дают корректных счётчиков в фильтрах.

Решение: **фильтруемые характеристики — нормализованы, описательные — в JSONB.**

```
attributes                        -- справочник характеристик
  id, code UNIQUE, name, unit
  value_type      VARCHAR(16)     -- string|number|bool|option
  is_filterable   BOOLEAN
  is_visible      BOOLEAN
  sort_order

attribute_options                 -- варианты для value_type='option'
  id, attribute_id FK, value, slug, sort_order

category_attributes               -- какие атрибуты показывать в фильтрах категории
  category_id FK, attribute_id FK, sort_order, is_required

product_attribute_values          -- значения (только фильтруемые)
  product_id FK, attribute_id FK
  value_string  VARCHAR(255) NULL
  value_number  NUMERIC(14,4) NULL
  value_bool    BOOLEAN NULL
  option_id     BIGINT NULL FK -> attribute_options(id)
  PK (product_id, attribute_id, COALESCE(option_id,0))
```

`products.specs JSONB` хранит всё остальное — то, что просто выводится таблицей в карточке и никогда не участвует в фильтрах. Материал упаковки, страна происхождения, произвольные примечания из Excel. Никаких миграций при добавлении новой строки в описание.

Правило переноса: характеристика, по которой пользователь захочет фильтровать → в `attributes`. Всё остальное → в `specs`.

### 6.4 Цены

**Модель прайс-листов + ступени внутри прайс-листа.** Это на один уровень абстракции больше, чем просили, но именно этот уровень нужен B2B при выходе в другие города и при появлении дилерских цен.

```
price_lists
  id, code UNIQUE, name
  currency        CHAR(3) DEFAULT 'KZT'
  region_id       BIGINT NULL FK -> regions(id)   -- прайс для города/региона
  customer_group  VARCHAR(32) NULL                -- retail|dealer|partner (на будущее)
  is_default      BOOLEAN
  valid_from, valid_to  TIMESTAMPTZ NULL
  is_active       BOOLEAN

product_prices
  id
  product_id      BIGINT FK
  price_list_id   BIGINT FK
  min_qty         NUMERIC(14,3) NOT NULL DEFAULT 1
  max_qty         NUMERIC(14,3) NULL              -- NULL = без верхней границы
  price           NUMERIC(14,2) NOT NULL
  qty_range       NUMRANGE GENERATED              -- для ограничения пересечений
  external_id     VARCHAR(64) NULL
  updated_at
```

Ваш пример превращается в четыре строки одного прайс-листа:

| min_qty | max_qty | price |
| ------- | ------- | ----- |
| 1       | 9       | 3500  |
| 10      | 49      | 3200  |
| 50      | 99      | 2900  |
| 100     | NULL    | 2600  |

**Ограничение целостности** — не полагаться на код приложения:

```sql
ALTER TABLE product_prices ADD CONSTRAINT no_overlapping_tiers
  EXCLUDE USING gist (
    product_id WITH =, price_list_id WITH =, qty_range WITH &&
  );
```

Пересекающиеся диапазоны становятся физически невозможны. Это тот случай, когда база должна защищать себя сама — цену будут править менеджеры, импорты и (потом) 1С.

**Четыре режима цены** обслуживаются полем `products.price_mode`:

| `price_mode` | Строк в `product_prices`        | Отображение на сайте                       |
| ------------ | ------------------------------- | ------------------------------------------ |
| `fixed`      | одна, `min_qty=1, max_qty=NULL` | `3 500 ₸`                                  |
| `from`       | одна или несколько              | `от 2 600 ₸`                               |
| `tiered`     | несколько                       | таблица ступеней + «от N ₸» в списке       |
| `on_request` | ноль                            | «Цена по запросу», кнопка «Запросить цену» |

Расчёт цены — **всегда на backend**, единая функция `resolve_price(product, qty, price_list)`. На фронте её дублировать нельзя: в момент подключения дилерских цен фронт покажет не то.

Хранение истории цен на первом этапе не делаем, но `product_prices.updated_at` + `audit_log` дают минимальную прослеживаемость. Полноценная история (`product_price_history`) добавляется позже без изменения схемы.

### 6.5 Остатки

```
warehouses
  id, code UNIQUE, name
  region_id     BIGINT NULL FK -> regions(id)
  external_id   VARCHAR(64) NULL          -- склад в 1С
  is_active     BOOLEAN

stocks
  product_id    BIGINT FK
  warehouse_id  BIGINT FK
  quantity      NUMERIC(14,3) NOT NULL DEFAULT 0
  reserved      NUMERIC(14,3) NOT NULL DEFAULT 0
  updated_at    TIMESTAMPTZ
  source        VARCHAR(16) DEFAULT 'manual'
  PK (product_id, warehouse_id)
```

На старте — один склад в Алматы. Структура «товар × склад» с самого начала избавляет от миграции при появлении второго города.

**Публичный статус вычисляется, а не хранится:**

```
available = SUM(quantity - reserved) по активным складам региона

available > threshold_low   → in_stock       "В наличии"
0 < available <= threshold  → low_stock      "Мало на складе"  (опционально)
available = 0               → out_of_stock   "Нет в наличии"
price_mode = on_request     → on_request     "Под заказ"
```

Порог `threshold_low` — в `settings`, чтобы менеджер менял его без деплоя. Плюс поле `products.stock_display_override` (`auto|in_stock|out_of_stock|on_order`) для ручного управления в исключительных случаях — оно понадобится, гарантированно.

**Публичный API не отдаёт число.** Только статус. Точный остаток — это коммерческая информация, по которой конкурент оценивает ваши обороты. В админке — точное число.

`reserved` пока не используется (заявки не резервируют), но поле закладываем — резервирование под заявку появится вместе с 1С.

### 6.6 Изображения

```
media_files                       -- физический файл в R2
  id            BIGINT PK
  uuid          UUID UNIQUE
  storage_key   VARCHAR(512) UNIQUE   -- products/9f2c.../original.jpg
  bucket        VARCHAR(64)
  mime_type     VARCHAR(64)
  size_bytes    BIGINT
  width, height INT NULL
  checksum      VARCHAR(64) NULL      -- sha256, дедупликация
  status        VARCHAR(16)           -- pending|processing|ready|failed
  variants      JSONB DEFAULT '{}'    -- {"large":{"key":"...","w":1200,"h":900}, ...}
  uploaded_by_id BIGINT FK
  created_at

product_media                     -- связь с товаром
  id
  product_id     BIGINT FK
  media_file_id  BIGINT FK
  kind           VARCHAR(16) DEFAULT 'photo'  -- photo|scheme|drawing|certificate
  sort_order     INT DEFAULT 0
  alt_text       VARCHAR(255) NULL
  is_primary     BOOLEAN DEFAULT false
```

**Почему две таблицы, а не одна.** Один и тот же файл (схема, логотип) может использоваться в нескольких товарах и в контентных страницах. `media_files` — это медиатека, `product_media` — привязка с порядком и подписью. Разделение также позволяет удалить товар, не теряя файл, и наоборот.

**Никаких URL в базе.** Только `storage_key`. URL собирается на backend из `settings.CDN_BASE_URL + storage_key` в момент сериализации. Смена CDN-домена или переезд с R2 на другой провайдер — это правка одной переменной окружения, а не `UPDATE` по миллиону строк.

`kind` разделяет фотографии и чертежи — это ваше требование про «схемы/чертежи товара». В UI они выводятся в разных блоках галереи.

`is_primary` — обложка карточки. Частичный уникальный индекс `UNIQUE(product_id) WHERE is_primary`.

### 6.7 Заявки

⚠️ **Рекомендую объединить «заявки» и «лиды» в одну таблицу с полем `kind`.**

Обоснование: у них полностью совпадают контактные данные, статусная модель, воронка, комментарии, уведомления и права доступа. Отличается только наличие товарных позиций. Две таблицы означают два набора статусов, два набора уведомлений, два отчёта и вечный вопрос «а где искать эту заявку». В админке это по-прежнему два раздела — просто с разным фильтром по `kind`.

```
requests
  id               BIGINT PK
  uuid             UUID UNIQUE          -- публичный идентификатор
  number           VARCHAR(24) UNIQUE   -- человекочитаемый: R-2026-000142
  kind             VARCHAR(24)          -- cart | custom_product | callback
  status           VARCHAR(24)          -- new|in_progress|quoted|won|lost|spam
  -- контакты
  customer_name    VARCHAR(255)
  phone            VARCHAR(32)
  email            VARCHAR(255) NULL
  company          VARCHAR(255) NULL
  bin              VARCHAR(12) NULL     -- БИН для B2B
  city             VARCHAR(120) NULL
  region_id        BIGINT NULL FK
  comment          TEXT NULL            -- в т.ч. описание товара для kind=custom_product
  preferred_contact VARCHAR(16) NULL    -- phone|whatsapp|email|telegram
  -- служебное
  source           VARCHAR(64)          -- catalog_cart|not_found_form|product_page|whatsapp
  utm              JSONB DEFAULT '{}'
  page_url         VARCHAR(1000) NULL
  ip_hash          VARCHAR(64) NULL     -- хеш, не сам IP
  user_agent       VARCHAR(500) NULL
  idempotency_key  VARCHAR(64) UNIQUE NULL
  consent_at       TIMESTAMPTZ NULL     -- согласие на обработку ПДн
  total_estimate   NUMERIC(14,2) NULL   -- расчёт на момент подачи
  assigned_to_id   BIGINT NULL FK -> users(id)
  external_id      VARCHAR(64) NULL     -- ID документа в 1С после выгрузки
  exported_at      TIMESTAMPTZ NULL
  created_at, updated_at, deleted_at

request_items
  id
  request_id       BIGINT FK ON DELETE CASCADE
  product_id       BIGINT NULL FK ON DELETE SET NULL   -- ссылка, не источник данных
  -- СНАПШОТ на момент подачи заявки:
  sku_snapshot     VARCHAR(64)
  name_snapshot    VARCHAR(500)
  unit_snapshot    VARCHAR(16)
  quantity         NUMERIC(14,3)
  unit_price_snapshot  NUMERIC(14,2) NULL
  line_total_snapshot  NUMERIC(14,2) NULL
  price_mode_snapshot  VARCHAR(16)
  note             TEXT NULL

request_comments
  id, request_id FK, user_id FK, body TEXT, is_internal BOOLEAN, created_at

request_status_history
  id, request_id FK, from_status, to_status, user_id FK, comment, created_at
```

**Снапшот позиций — обязателен.** Заявка — юридически и коммерчески значимый документ. Через полгода товар переименуют, цену поднимут, позицию снимут с производства — заявка должна показывать то, что видел клиент в момент отправки. Джойн на живой `products` для отображения состава заявки — классическая ошибка, которая обнаруживается через год спором с клиентом о цене.

**`idempotency_key`** приходит с фронта (UUID, сгенерированный при открытии формы). Двойной клик, повторная отправка при таймауте, ретрай мобильной сети — всё это не создаст дубли.

**Антиспам** для публичных форм: honeypot-поле, минимальное время заполнения формы, rate limit по IP (Redis), Cloudflare Turnstile при росте спама. Статус `spam` вместо удаления.

### 6.8 Пользователи

```
users
  id, uuid UNIQUE
  email           CITEXT UNIQUE
  password_hash   VARCHAR(255)          -- argon2id
  full_name       VARCHAR(255)
  phone           VARCHAR(32) NULL
  role            VARCHAR(32)           -- см. раздел 12
  is_active       BOOLEAN DEFAULT true
  last_login_at   TIMESTAMPTZ NULL
  failed_login_count SMALLINT DEFAULT 0
  locked_until    TIMESTAMPTZ NULL
  password_changed_at TIMESTAMPTZ
  created_at, updated_at, deleted_at

refresh_tokens
  id, user_id FK
  token_hash      VARCHAR(255) UNIQUE   -- хеш, не сам токен
  family_id       UUID                  -- для rotation-детекции переиспользования
  expires_at, revoked_at, created_at
  user_agent, ip_hash

api_keys                                -- для 1С и других систем, не для людей
  id, name, key_hash, scopes JSONB
  is_active, last_used_at, expires_at
```

Клиентских аккаунтов на первом этапе нет — заявку оставляют без регистрации. Таблица `users` только для сотрудников. Личный кабинет B2B-клиента появится позже отдельной сущностью `customers`; смешивать сотрудников и клиентов в одной таблице — плохая идея (разные права, разные правила блокировки, разная политика паролей).

---

## 7. Интеграция с 1С

> **Статус на этапе 9.** Раздел ниже — исходный проект. Основа обмена
> **реализована** по нему: эндпоинты 7.3, аутентификация по API-ключу,
> идемпотентность, построчный отчёт, `sync_log`. Боевой обмен выключен
> настройкой `ONE_C_INTEGRATION_ENABLED` и включается только после
> сверки контракта с выгрузкой конкретной конфигурации 1С.
> Что именно сделано и что требуется от заказчика —
> [`docs/integrations.md`](integrations.md).

### 7.1 Поля в схеме

- `external_id VARCHAR(64) NULL UNIQUE` — GUID объекта 1С. На: `products`, `categories`, `attributes`, `warehouses`, `price_lists`, `product_prices`, `requests`. Уникальный частичный индекс `WHERE external_id IS NOT NULL`.
- `sku` как **бизнес-ключ** для сопоставления там, где GUID ещё не проставлен (первичная загрузка, Excel).
- `sync_source VARCHAR(16)` — кто последний записал: `manual` / `1c` / `excel`.
- `synced_at TIMESTAMPTZ` — время последней синхронизации.
- `updated_at` — для инкрементального обмена по времени.

### 7.2 Разделение владения полями

Самая частая причина провала таких интеграций — обе системы считают себя главной, и данные затираются по кругу. Матрицу нужно зафиксировать письменно до начала интеграции:

| Данные                      | Мастер                    | Комментарий                                                          |
| --------------------------- | ------------------------- | -------------------------------------------------------------------- |
| Артикул (`sku`)             | 1С                        | Сайт не создаёт артикулы                                             |
| Название                    | 1С                        | Сайт может иметь отдельное `marketing_name`                          |
| Цены                        | 1С                        | Сайт только читает                                                   |
| Остатки                     | 1С                        | Сайт только читает                                                   |
| Единица измерения           | 1С                        |                                                                      |
| Категории (структура)       | обсуждается               | Часто удобнее вести на сайте: в 1С структура учётная, а не витринная |
| Описание, SEO               | Сайт                      | 1С не трогает                                                        |
| Изображения                 | Сайт                      | 1С не трогает                                                        |
| Характеристики для фильтров | Сайт                      |                                                                      |
| Заявки                      | Сайт создаёт, 1С забирает | Односторонний поток вверх                                            |

Рекомендация по категориям: **дерево категорий вести на сайте**, а связь с 1С — через сопоставление групп номенклатуры. Учётная структура 1С почти никогда не годится как витрина.

### 7.3 Модель обмена

**Pull-модель: инициатор — 1С.** Причина практическая: 1С обычно стоит внутри офисной сети за NAT, без белого IP, и её недоступность не должна ронять сайт. Сайт публикует эндпоинты, 1С по расписанию их дёргает.

```
POST /api/v1/integration/catalog/products/bulk-upsert    (1С → сайт)
POST /api/v1/integration/catalog/categories/bulk-upsert
POST /api/v1/integration/pricing/bulk-upsert
POST /api/v1/integration/inventory/bulk-upsert           -- самый частый: остатки
GET  /api/v1/integration/requests?status=new&since=...   (сайт → 1С)
POST /api/v1/integration/requests/{uuid}/ack             -- подтверждение приёма
GET  /api/v1/integration/health
```

Требования к эндпоинтам:

- **Идемпотентность.** Повторная отправка того же пакета не создаёт дублей и не ломает состояние. Ключ — `external_id`, при его отсутствии — `sku`.
- **Батчи.** До 500–1000 позиций за запрос, ответ — построчный результат: `created` / `updated` / `skipped` / `error` с причиной. 1С должна понимать, что именно не прошло.
- **Частичный успех.** Одна битая строка не отменяет весь пакет. Транзакция — на пакет, но с предварительной валидацией и отбраковкой битых строк в отчёт.
- **Отдельная аутентификация:** API-ключ (`api_keys`) в заголовке + allowlist по IP. Не JWT пользователя, не сессия.
- **Логирование в `sync_log`:** направление, эндпоинт, объём, длительность, ошибки. Без этого разбор «почему остатки не обновились» превращается в гадание.
- **Свой DTO-контракт, не структура 1С.** Эндпоинты принимают нейтральный JSON. Преобразование форматов — задача обработки на стороне 1С или тонкого адаптера. Если формат 1С протечёт в схему API — вы навсегда привязаны к текущей конфигурации 1С.

### 7.4 Что не делать

- Не подключать 1С напрямую к PostgreSQL. Только через API.
- Не использовать стандартный обмен CommerceML вслепую — он тяжёл и заточен под типовые конфигурации; решение принимается после того, как станет известна конфигурация 1С заказчика.
- Не откладывать `external_id` «на потом». Добавить поле в пустую таблицу бесплатно, ретроспективно сопоставить 3000 товаров — неделя ручной работы.

---

## 8. Object Storage + CDN

### 8.1 Схема

```
Cloudflare R2 bucket: oinau-pro-media
│
├── products/{product_uuid}/{media_uuid}/
│     ├── original.jpg          ← приватный префикс, не раздаётся
│     ├── large.webp     1600px
│     ├── medium.webp     800px
│     ├── small.webp      400px
│     └── thumb.webp      200px
├── content/{uuid}/...          ← баннеры, страницы
└── imports/{job_uuid}.xlsx     ← приватно, TTL 90 дней

Публичный доступ: cdn.oinau-pro.kz  →  R2 custom domain
```

**Почему R2, а не S3.** Нулевая плата за egress — решающий фактор для каталога с картинками. Плюс встроенный CDN Cloudflare и S3-совместимый API (значит, локально можно подменить MinIO, а при необходимости переехать на любой S3-провайдер).

**Два уровня доступа:**

- Обработанные варианты (`large`, `medium`, `small`, `thumb`) — публичны через `cdn.oinau-pro.kz`, `Cache-Control: public, max-age=31536000, immutable`.
- Оригиналы — приватны, доступны только backend'у по presigned URL. Оригинал может весить 8 МБ и содержать EXIF; отдавать его клиентам незачем.

**Иммутабельные ключи.** Ключ включает UUID и никогда не перезаписывается. Замена изображения = новый `media_file` с новым ключом. Это позволяет кэшировать вечно и не заниматься инвалидацией CDN — самой болезненной операцией в таких системах.

**Форматы.** Основной — WebP (поддержка >96% браузеров, экономия 25–35% против JPEG). JPEG-фолбэк генерировать не нужно. AVIF — опционально позже.

### 8.2 ⚠️ Альтернатива генерации вариантов

Собственная генерация вариантов в воркере (Pillow / pillow-simd / libvips) — рабочее решение, и я его закладываю по умолчанию. Но стоит рассмотреть **Cloudflare Images Transformations**: варианты генерируются на edge по URL-параметрам, воркер и хранение четырёх копий каждого файла не нужны.

|             | Свой воркер                    | Cloudflare Transformations         |
| ----------- | ------------------------------ | ---------------------------------- |
| Стоимость   | CPU сервера                    | Оплата за уникальные трансформации |
| Сложность   | Воркер, Pillow, retry, статусы | Практически ноль                   |
| Контроль    | Полный                         | Ограничен параметрами API          |
| Зависимость | Нет                            | Привязка к Cloudflare              |
| Хранение    | ×4–5 объёма                    | ×1 (только оригинал)               |

Рекомендация: **проектировать схему так, чтобы работали оба варианта.** Поле `media_files.variants JSONB` может либо хранить реальные ключи (свой воркер), либо оставаться пустым, а URL собираться с параметрами трансформации. Решение принимается на этапе реализации медиа-модуля после оценки тарифов.

### 8.3 Локальная разработка

Локально вместо R2 — **MinIO** в docker-compose. Тот же S3 API, тот же код, другая переменная окружения `S3_ENDPOINT_URL`. Разработчику не нужны боевые ключи Cloudflare, и локальная работа не мусорит в продовый бакет.

---

## 9. Поток загрузки изображения

```
┌────────┐                ┌─────────┐            ┌────────┐        ┌────────┐
│ Admin  │                │ FastAPI │            │   R2   │        │ Worker │
└───┬────┘                └────┬────┘            └───┬────┘        └───┬────┘
    │                          │                     │                 │
    │ 1. POST /admin/media/upload-intent             │                 │
    │    {filename, mime, size}│                     │                 │
    │─────────────────────────►│                     │                 │
    │                          │ проверка: роль,     │                 │
    │                          │ mime в whitelist,   │                 │
    │                          │ size <= 15 MB,      │                 │
    │                          │ rate limit          │                 │
    │                          │ INSERT media_files  │                 │
    │                          │   status=pending    │                 │
    │                          │ генерация ключа     │                 │
    │ 2. {media_uuid, upload_url, expires_in: 600}   │                 │
    │◄─────────────────────────│                     │                 │
    │                                                │                 │
    │ 3. PUT upload_url  (файл идёт НАПРЯМУЮ в R2)   │                 │
    │───────────────────────────────────────────────►│                 │
    │                                                │                 │
    │ 4. POST /admin/media/{uuid}/complete           │                 │
    │─────────────────────────►│                     │                 │
    │                          │ 5. HEAD объекта     │                 │
    │                          │────────────────────►│                 │
    │                          │ проверка: существует,                 │
    │                          │ размер, magic bytes │                 │
    │                          │ status=processing   │                 │
    │                          │ 6. enqueue задачу   │                 │
    │                          │───────────────────────────────────────►│
    │ 7. {status: processing}  │                     │                 │
    │◄─────────────────────────│                     │  8. GET original│
    │                                                │◄────────────────│
    │                                                │  9. PUT variants│
    │                                                │◄────────────────│
    │                          │ 10. status=ready, variants, w, h      │
    │                          │◄──────────────────────────────────────│
    │ 11. polling / SSE → готово                     │                 │
    │◄─────────────────────────│                     │                 │
    │                                                │                 │
    │ 12. Клиент: GET cdn.oinau-pro.kz/products/.../medium.webp        │
    │      backend не участвует                      │                 │
```

### Меры безопасности на каждом шаге

| Шаг | Контроль                                                                                                                                                  |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Только роль с правом `media.upload`. Rate limit на выдачу presigned URL                                                                                   |
| 1   | Whitelist MIME: `image/jpeg`, `image/png`, `image/webp`. Расширение клиента игнорируется                                                                  |
| 1   | Имя файла клиента не используется в ключе. Ключ = UUID. Никаких `../`, кириллицы, пробелов                                                                |
| 2   | Срок жизни presigned URL — 10 минут. Только метод `PUT`, только конкретный ключ                                                                           |
| 3   | Файл не проходит через FastAPI: не занимает воркеры, не упирается в лимиты прокси                                                                         |
| 5   | `HEAD` подтверждает реальный размер. ⚠️ Если R2 не даёт задать `content-length-range` в presigned PUT, объект превышающего размера удаляется на этом шаге |
| 5   | Проверка magic bytes: заявленный `image/png` должен начинаться с сигнатуры PNG. Защита от загрузки скриптов под видом картинки                            |
| 9   | EXIF вырезается (в нём бывают геометки и данные о съёмке)                                                                                                 |
| —   | Бакет не имеет публичного `LIST`. Публично читаются только префиксы вариантов                                                                             |
| —   | Ключи R2 хранятся только в переменных окружения backend/worker. У админки их нет                                                                          |

### Уборка мусора

Записи `media_files` со статусом `pending` старше 24 часов и объекты без соответствующей записи в БД удаляются периодической задачей. Без этого бакет за год зарастёт брошенными загрузками.

---

## 10. Поток создания заявки

```
┌─────────┐         ┌──────────┐        ┌──────────┐       ┌────────┐
│ Browser │         │ FastAPI  │        │ Postgres │       │ Worker │
└────┬────┘         └────┬─────┘        └────┬─────┘       └───┬────┘
     │                   │                   │                 │
     │ Корзина-заявка живёт в localStorage (без сервера)        │
     │                   │                   │                 │
     │ POST /api/v1/public/requests                             │
     │ {kind, items[], contact, consent, idempotency_key, utm}  │
     │──────────────────►│                   │                 │
     │                   │ rate limit (Redis, по IP)            │
     │                   │ honeypot / Turnstile                 │
     │                   │ Pydantic-валидация                   │
     │                   │ проверка idempotency_key             │
     │                   │                   │                 │
     │                   │ ┌── ТРАНЗАКЦИЯ ──────────────────┐  │
     │                   │ │ SELECT товары и актуальные цены│  │
     │                   │ │ пересчёт цен НА СЕРВЕРЕ        │  │
     │                   │ │ INSERT requests                │  │
     │                   │ │ INSERT request_items (снапшот) │  │
     │                   │ │ INSERT request_status_history  │  │
     │                   │ │ INSERT notification_outbox ×2  │  │
     │                   │ └── COMMIT ────────────────────────┘ │
     │                   │──────────────────►│                 │
     │                   │                   │                 │
     │ 201 {number, uuid}│                   │                 │
     │◄──────────────────│                   │                 │
     │  ← пользователь уже видит "Заявка принята"               │
     │                   │                   │                 │
     │                   │        воркер читает outbox         │
     │                   │◄────────────────────────────────────│
     │                   │                   │  Telegram API   │──►📱
     │                   │                   │  SMTP           │──►✉️
     │                   │                   │  UPDATE outbox  │
     │                   │                   │  sent_at / retry│
```

### Ключевое решение: transactional outbox

Уведомление **не отправляется в HTTP-обработчике**. Причины:

1. Telegram или SMTP недоступны → пользователь получает 500 и уходит, хотя заявка нужна бизнесу. Заявка теряется.
2. Ответ пользователю задерживается на 1–3 секунды сетевого запроса.
3. При ретрае клиента появляются дубли уведомлений.

Запись в `notification_outbox` идёт **в той же транзакции**, что и заявка. Либо есть и заявка, и задание на уведомление, либо нет ничего. Промежуточных состояний не существует.

```
notification_outbox
  id, uuid
  event_type    VARCHAR(64)     -- request.created | request.status_changed
  channel       VARCHAR(24)     -- telegram | email
  payload       JSONB
  status        VARCHAR(16)     -- pending|processing|sent|failed
  attempts      SMALLINT DEFAULT 0
  next_retry_at TIMESTAMPTZ
  last_error    TEXT NULL
  created_at, sent_at
```

Воркер: экспоненциальный backoff (1 мин → 5 → 15 → 60), максимум 6 попыток, затем `failed` + алерт администратору. Заявка при этом **уже в базе** и видна в админке — это главное.

⚠️ **FastAPI `BackgroundTasks` для этого не подходит.** Они выполняются в том же процессе и теряются при рестарте/деплое. Как временное решение на самом первом этапе допустимы, но только вместе с таблицей outbox — тогда переход на настоящий воркер не потребует изменений в бизнес-логике.

### Пересчёт цен на сервере

Цены, пришедшие с фронта, **игнорируются полностью**. Backend заново считает `resolve_price(product, qty, price_list)` и пишет в снапшот свой результат. Иначе цену можно подменить в DevTools, и менеджер получит заявку с ценой 1 ₸.

### WhatsApp

Плавающая кнопка — ссылка `https://wa.me/<номер>?text=<преднастроенный текст>`. Номер и шаблон текста берутся из `settings` через публичный эндпоинт `/api/v1/public/settings` и кэшируются на фронте (ISR, revalidate 5 мин). Менять номер можно из админки без деплоя.

Полезная деталь: на странице товара подставлять артикул в текст сообщения — менеджер сразу видит, о чём речь.

---

## 11. API-модули

Три изолированные поверхности. У каждой — свои middleware, CORS, rate limit и схема аутентификации.

### 11.1 Public API — `/api/v1/public/*`

Без авторизации. Read-only, кроме создания заявок. Агрессивно кэшируется.

```
GET  /categories                       дерево категорий
GET  /categories/{slug}
GET  /products                         фильтры, сортировка, курсорная пагинация
GET  /products/{slug}
GET  /products/{slug}/related
GET  /search?q=                        + /search/suggest для автокомплита
GET  /filters?category=                доступные фильтры и счётчики (фасеты)
POST /cart/validate                    пересчёт корзины: актуальные цены и наличие
POST /requests                         создание заявки (rate limited)
GET  /content/pages/{slug}
GET  /content/banners?placement=
GET  /content/faq
GET  /settings                         контакты, WhatsApp, регион, соцсети
GET  /regions
POST /subscribe                        (на будущее)
```

Пагинация — **курсорная** (`?cursor=&limit=`), не `offset`. На больших каталогах `OFFSET 10000` деградирует, и это неприятно обнаруживать в проде.

`POST /cart/validate` — важный эндпоинт: корзина хранится в localStorage, и перед отправкой заявки её нужно сверить с актуальным состоянием (товар мог исчезнуть, цена измениться).

### 11.2 Admin API — `/api/v1/admin/*`

JWT, RBAC на каждом эндпоинте, аудит всех мутаций, no-cache.

```
auth/          login, refresh, logout, me, change-password
catalog/       products CRUD, bulk-actions, categories, attributes
pricing/       price-lists, product-prices (bulk)
inventory/     stocks, warehouses, adjustments
media/         upload-intent, complete, library, attach/detach, reorder
requests/      list (фильтры/поиск), detail, status, assign, comments, export
content/       pages, banners, faq
settings/      получение и обновление настроек
users/         CRUD, роли, блокировка
imports/       upload, dry-run, apply, jobs, errors        (позже)
exports/       products.xlsx, requests.xlsx                (позже)
dashboard/     статистика: новые заявки, конверсия, топ-товары
audit/         журнал действий
```

### 11.3 Integration API — `/api/v1/integration/*`

API-ключ + IP allowlist. Нет в публичной документации. Отдельный rate limit (высокий).

```
catalog/products/bulk-upsert
catalog/categories/bulk-upsert
pricing/bulk-upsert
inventory/bulk-upsert
requests?status=new&since=
requests/{uuid}/ack
health
```

### 11.4 Служебное

```
GET /health          liveness
GET /health/ready    readiness: БД, Redis, R2
GET /metrics         Prometheus (закрыт извне)
GET /docs            Swagger — ТОЛЬКО в dev, в проде отключить
```

⚠️ Открытый `/docs` в проде выдаёт полную карту вашего admin API. Отключается через `docs_url=None` при `ENV=production`.

---

## 12. Система ролей

**Роли — для назначения, permissions — для проверок.** В коде никогда не проверяется `if user.role == "admin"`, проверяется `require("product.update")`. Это позволяет менять состав прав роли без правки эндпоинтов.

| Роль              | Назначение               | Права                                                   |
| ----------------- | ------------------------ | ------------------------------------------------------- |
| `superadmin`      | Владелец/техадмин        | Всё, включая пользователей, роли, настройки, API-ключи  |
| `admin`           | Руководитель             | Всё, кроме управления superadmin и API-ключами          |
| `manager`         | Менеджер по продажам     | Заявки: полный доступ. Каталог: чтение. Остатки: чтение |
| `content_manager` | Контент/каталог          | Каталог, медиа, контент, импорт. Заявки: без доступа    |
| `viewer`          | Наблюдатель, бухгалтерия | Только чтение                                           |

Плюс **не-человеческие субъекты** — `api_keys` со `scopes` (`catalog:write`, `inventory:write`, `requests:read`). 1С не должна получать учётную запись пользователя: у неё другой жизненный цикл, другая ротация секретов и она не должна попадать в списки сотрудников.

### Реализация

- Поле `users.role VARCHAR(32)` + константный словарь `ROLE_PERMISSIONS` в коде. Отдельные таблицы `roles`/`permissions` на этом масштабе — избыточная гибкость, которая никому не понадобится, но которую придётся поддерживать.
- FastAPI-зависимость: `Depends(require_permissions("request.update"))`.
- Точечные ограничения на уровне данных: менеджер видит все заявки, но менять статус может только у назначенных на него (`assigned_to_id`) — если такое правило потребуется бизнесу.
- Все мутации в админке пишутся в `audit_log`: кто, что, когда, старое и новое значение (JSONB diff).

### Аутентификация

- **Access token** — JWT, 15 минут, в памяти приложения (не в localStorage).
- **Refresh token** — 7–30 дней, **httpOnly + Secure + SameSite=Strict cookie**, в БД хранится только хеш.
- **Refresh token rotation** с детекцией переиспользования: если пришёл уже использованный refresh — отзывается вся «семья» токенов (`family_id`). Это стандартная защита от кражи токена.
- Хеширование паролей — **argon2id** (предпочтительнее bcrypt: устойчив к GPU-атакам, нет ограничения в 72 байта).
- Блокировка после N неудачных попыток + rate limit на `/auth/login`.
- 2FA (TOTP) — не сейчас, но `users` под неё расширяется без миграции данных.

⚠️ **Access token в localStorage — уязвимость к XSS.** Схема выше (access в памяти + refresh в httpOnly cookie) немного сложнее в реализации, но это тот компромисс, на который стоит пойти для админки коммерческого проекта.

---

## 13. Docker-инфраструктура для разработки

### 13.1 Состав `compose.dev.yaml`

| Сервис       | Образ                | Порт      | Назначение                            |
| ------------ | -------------------- | --------- | ------------------------------------- |
| `postgres`   | `postgres:16-alpine` | 5432      | БД, named volume                      |
| `redis`      | `redis:7-alpine`     | 6379      | Очереди, rate limit, кэш              |
| `minio`      | `minio/minio`        | 9000/9001 | Локальная замена R2 (S3 API)          |
| `minio-init` | `minio/mc`           | —         | Создаёт бакет и политики при старте   |
| `backend`    | локальный build      | 8000      | `uvicorn --reload`, код примонтирован |
| `worker`     | тот же образ         | —         | ARQ, `--watch`                        |
| `web`        | локальный build      | 3000      | `next dev`                            |
| `admin`      | локальный build      | 3001      | `next dev`                            |
| `mailpit`    | `axllent/mailpit`    | 8025      | Ловит все письма, веб-интерфейс       |

Опционально: `adminer` или `pgadmin` для просмотра БД.

### 13.2 Принципы

- **Один Dockerfile на приложение, multi-stage.** Стадия `development` с hot-reload, стадия `production` со сборкой и non-root пользователем. Не два разных Dockerfile — они разъезжаются.
- **Код монтируется томом в dev, копируется в образ в prod.**
- **Зависимости кэшируются отдельным слоем** (`pyproject.toml`/`package.json` копируются до кода) — иначе каждая правка кода пересобирает всё.
- **`node_modules` и `.venv` — в анонимных томах**, не пробрасываются с хоста (разные платформы, разные бинарники).
- **Healthcheck у `postgres` и `redis`**, `depends_on: condition: service_healthy` у backend. Иначе backend стартует раньше БД и падает.
- **Prod-образ Next.js — `output: 'standalone'`**, иначе образ весит гигабайт.
- **Никаких секретов в `docker-compose` и Dockerfile.** Только `.env` (в `.gitignore`) + `.env.example` в репозитории.
- **Миграции не запускаются автоматически при старте контейнера.** Отдельная команда/шаг деплоя. Автомиграции при старте нескольких реплик = гонка и повреждённая схема.

### 13.3 Makefile

```
make up            поднять окружение
make down
make logs s=backend
make migrate       alembic upgrade head
make makemigration m="add price tiers"
make seed          демо-данные для разработки
make test
make lint          ruff + mypy + eslint
make gen-types     OpenAPI → packages/api-types
make shell         psql в контейнере
```

Один вход в проект. Новый разработчик должен запускаться командой `make up` без чтения инструкции на три страницы.

### 13.4 Продакшен

Тот же compose с профилем prod: backend без reload, за Traefik/Nginx, TLS от Let's Encrypt, Postgres с настроенным `pg_dump` по расписанию в отдельный бакет R2, ротация логов, `restart: unless-stopped`.

⚠️ **Резервное копирование — с первого дня, не «потом».** Ежедневный `pg_dump` в R2 с хранением 30 дней и **проверенным восстановлением**. Бэкап, который никогда не восстанавливали, бэкапом не является.

⚠️ **По хостингу:** shared-хостинг Hoster.kz для этого стека не подойдёт. Нужен VPS/Cloud минимум 2 vCPU / 4 ГБ RAM / 40 ГБ SSD. Изображения на диске не лежат (они в R2), поэтому диск нужен в основном под БД и логи.

---

## 14. Архитектурные ошибки, которых нужно избежать

### Данные

1. **Цена полем в `products`.** Через месяц придут ступенчатые цены, и это будет миграция с переписыванием половины API.
2. **`is_available BOOLEAN` в `products`.** Наличие — производная от остатков. Хранимый флаг рассинхронизируется с реальностью в первый же день работы 1С.
3. **`INTEGER` для количества.** Канат продаётся метрами. Дробные количества придут вместе с 1С.
4. **`FLOAT` для денег.** `0.1 + 0.2 != 0.3`. Только `NUMERIC`.
5. **Позиции заявки без снапшота.** Через полгода состав старой заявки будет показывать текущие названия и текущие цены — и это будет обнаружено в споре с клиентом.
6. **Одна категория на товар.** Ассортимент пересекается по разделам почти всегда.
7. **`ON DELETE CASCADE` от товара к позициям заявки.** Удаление товара не должно уничтожать историю.
8. **Отсутствие `external_id`.** Добавить поле сейчас — минута. Сопоставить тысячи товаров с 1С задним числом — недели.
9. **PostgreSQL `ENUM` для статусов.** Расширение enum — блокирующая миграция. `VARCHAR + CHECK` гибче.
10. **Пропуск структуры переводов.** Если казахская версия появится через год, ретрофит затронет каждую таблицу с текстом.

### Файлы

11. **Хранение изображений в репозитории или на диске приложения.** Git пухнет, деплой замедляется, масштабирование на две реплики ломается, откат теряет файлы.
12. **Проксирование картинок через FastAPI.** Каждый запрос картинки занимает воркер, который должен обрабатывать API. Одна страница каталога — это 20+ картинок.
13. **Хранение полных URL в БД.** Смена CDN превращается в массовый `UPDATE`.
14. **Перезапись файла по тому же ключу.** Кэши CDN и браузеров будут отдавать старую картинку неделями.
15. **Загрузка через backend вместо presigned URL.** Упирается в лимиты тела запроса, таймауты прокси и память процесса.
16. **Доверие к `Content-Type` и имени файла от клиента.** Классический вектор загрузки исполняемого файла.

### Логика и приложение

17. **Отправка Telegram/Email синхронно в обработчике.** Падение Telegram = потеря заявок.
18. **Расчёт цены на фронте.** Логика продублируется и разойдётся; цену можно будет подменить.
19. **Доверие ценам, пришедшим с клиента.** Всегда пересчитывать на сервере.
20. **Отсутствие идемпотентности форм.** Двойные клики и ретраи дают дубли заявок, менеджер звонит клиенту дважды.
21. **`OFFSET`-пагинация.** Деградирует и даёт дубли/пропуски при параллельных вставках.
22. **N+1 запросов** при выдаче списка товаров с изображениями и ценами. `selectinload` / `joinedload` с самого начала, плюс тест, считающий количество SQL-запросов.
23. **Смешивание синхронного и асинхронного SQLAlchemy.** Синхронный драйвер в async-эндпоинте блокирует event loop. Выбрать `asyncpg` и придерживаться его.
24. **Бизнес-логика в роутерах.** Роутер валидирует и делегирует. Логика — в сервисном слое, иначе её нельзя переиспользовать в воркере и импорте.

### Безопасность и эксплуатация

25. **`.env` в Git.** Один коммит — и ключи R2 нужно ротировать. `.gitignore` + `git-secrets`/pre-commit hook с первого дня.
26. **Открытый Swagger в продакшене.**
27. **`CORS: allow_origins=["*"]`** вместе с `allow_credentials=True` — распространённая связка, которую браузер не пропустит и которую пытаются «починить» отключением проверок.
28. **Access token в localStorage.**
29. **Отсутствие rate limit на публичных формах.** Спам-боты находят формы за считанные дни после индексации.
30. **Отсутствие бэкапов или непроверенное восстановление.**
31. **Автоматический прогон миграций при старте контейнера.**
32. **Отсутствие структурированного логирования и `request_id`.** Разбор инцидента без корреляции запросов — это чтение простыни текста.

### Проектные

33. **Попытка сделать всё сразу.** Разбиение на этапы (раздел 15) — часть архитектуры, а не формальность.
34. **Преждевременная микросервисность.** Один backend, один воркер. Разделять сервисы на этом масштабе — чистые издержки.
35. **Elasticsearch «на будущее».** Postgres FTS покрывает потребности до десятков тысяч SKU.
36. **Отсутствие ADR.** Через полгода никто не вспомнит, почему выбрана гибридная модель атрибутов. Короткие записи в `docs/adr/` экономят месяцы споров.

---

## 15. Последовательность этапов

Каждый этап — самостоятельный, завершённый и разворачиваемый результат. Никакой этап не начинается, пока предыдущий не работает.

| Этап     | Содержание                                                                                       | Результат                         |
| -------- | ------------------------------------------------------------------------------------------------ | --------------------------------- |
| **1** ✅ | Архитектура (этот документ)                                                                      | Согласованный план                |
| **2**    | Каркас: monorepo, Docker Compose, FastAPI-скелет, Alembic, `/health`, CI-линтеры, `.env.example` | `make up` поднимает окружение     |
| **3**    | Модели БД и миграции: каталог, цены, остатки, медиа, заявки, пользователи. Seed-данные           | Схема в PostgreSQL, ревью схемы   |
| **4**    | Аутентификация и RBAC: JWT + refresh rotation, argon2, роли, `audit_log`                         | Защищённый admin API              |
| **5**    | Admin API каталога: CRUD товаров, категорий, атрибутов, цен, остатков                            | Работающий API, покрытый тестами  |
| **6**    | Медиа: R2/MinIO, presigned upload, воркер вариантов, привязка к товарам                          | Полный поток загрузки изображений |
| **7**    | Public API: каталог, фильтры, поиск, карточка товара, настройки                                  | Готовый бэкенд витрины            |
| **8**    | Заявки: `POST /requests`, outbox, воркер, Email-уведомления, антиспам                            | Заявки принимаются и доходят      |
| **9**    | Админка (UI): авторизация, товары, категории, цены, остатки, медиа                               | Менеджер может наполнять каталог  |
| **10**   | Админка (UI): заявки, лиды, статусы, комментарии, дашборд                                        | Полноценная работа с заявками     |
| **11**   | Публичный сайт: главная, каталог, фильтры, карточка, корзина-заявка, формы, WhatsApp, SEO        | Сайт готов к запуску              |
| **12**   | Контент: страницы, баннеры, FAQ, настройки в админке                                             | Контент правится без деплоя       |
| **13**   | **Продакшен-запуск:** VPS, домены, TLS, CDN, бэкапы, мониторинг, Sentry                          | Сайт работает на oinau-pro.kz     |
| **14**   | Telegram-уведомления                                                                             | Заявки приходят в Telegram        |
| **15**   | Excel: импорт с dry-run, отчёт об ошибках, история, экспорт                                      | Массовая работа с каталогом       |
| **16**   | Подготовка к 1С: integration API, API-ключи, `sync_log`, документация контракта                  | Готовая точка подключения         |
| **17**   | Реальная интеграция с 1С (после изучения конфигурации заказчика)                                 | Автосинхронизация                 |
| **18+**  | Мультирегиональность, дилерские цены, личный кабинет, онлайн-оплата                              | По потребности бизнеса            |

**Точка запуска — этап 13.** Всё после него — развитие работающего продукта, а не условие старта. Это принципиально: сайт должен начать приносить заявки до того, как будет написана интеграция с 1С.

**Порядок неслучаен.** Backend опережает frontend, потому что фронт без API писать не по чему. Медиа идёт до публичного API, потому что карточка товара без изображений бессмысленна. Excel и Telegram — после запуска, потому что они улучшают процесс, но не блокируют его.

---

## Открытые вопросы к заказчику

Ответы нужны до этапа 3 (модели БД):

1. **Казахская версия сайта планируется?** Это определяет структуру всех текстовых полей.
2. **Какая конфигурация 1С?** УТ, УНФ, Бухгалтерия, самописная? Влияет на модель обмена на этапе 17.
3. **Планируются ли разные цены для разных категорий клиентов** (дилер / розница / партнёр)? Схема прайс-листов это поддерживает, но нужно понимать приоритет.
4. **Нужен ли личный кабинет B2B-клиента** в обозримой перспективе? Влияет на разделение `users` / `customers`.
5. **Кто будет наполнять каталог на старте** — вручную через админку или сразу через Excel? Влияет на приоритет этапа 15.
6. **Есть ли требования к юрлицу в заявке** (БИН, форма собственности, счёт на оплату)?
7. **Ожидаемое количество заявок в день?** Влияет на решения по мониторингу и инфраструктуре.

---

## Приложение А. Ответы на открытые вопросы (зафиксировано перед этапом 2)

| #   | Вопрос              | Ответ                                                                                        | Влияние на схему                                                                                                                  |
| --- | ------------------- | -------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Казахская версия    | На старте только русский. Структура переводов закладывается сразу, KZ-контент не заполняется | Таблицы `*_translations` создаются на этапе 3 и заполняются одной локалью `ru`. `SUPPORTED_LOCALES` — настройка                   |
| 2   | Конфигурация 1С     | Неизвестна. Реальный обмен проектируется отдельно                                            | Закладываются `external_id`, `sku`, `sync_source`, `synced_at`, префикс `/api/v1/integration`. Кода интеграции нет                |
| 3   | Прайс-листы         | В интерфейсе на старте не нужны, в схеме — остаются                                          | Создаётся один прайс-лист `default`. Админка правит цены, не показывая выбор прайс-листа. Дилерские цены добавляются без миграции |
| 4   | Личный кабинет B2B  | Не нужен. Заявка без регистрации                                                             | `users` — только сотрудники. Будущая `customers` — отдельная таблица, не смешивается                                              |
| 5   | Наполнение каталога | Вручную через админку. Excel — отдельный этап                                                | Приоритет этапа 9 выше этапа 15                                                                                                   |
| 6   | Поля заявки         | Обязательные: имя, телефон. Опциональные: компания, БИН, email, город, комментарий           | В `requests` обязательны только `customer_name` и `phone`. Валидация телефона в формате KZ                                        |
| 7   | Нагрузка            | 100–200 заявок в день без изменения архитектуры                                              | Запас многократный: узкое место — не заявки, а выдача каталога. Решается кэшированием и CDN                                       |
| 8   | Статусы наличия     | «В наличии» / «Нет в наличии» / «Цена по запросу»                                            | Публичный API отдаёт `in_stock` / `out_of_stock` / `on_request`. Точное число — только в admin API                                |

**Оценка нагрузки.** 200 заявок в день — это порядка 8 записей в час. Определяющей нагрузкой становится не запись заявок, а чтение каталога: при 5000 товаров и активном трафике это тысячи запросов в час. Заложенная схема (курсорная пагинация, кэш публичного API, изображения через CDN мимо backend) держит этот профиль с запасом на одном VPS.

**Регион.** Алматы задан как значение настройки `DEFAULT_REGION_CODE`, а не константа в коде. Таблица `regions`, привязка складов и прайс-листов к региону создаются на этапе 3 — добавление второго города не потребует миграции.

---

## Приложение Б. Фактическая структура БД (этап 3, реализовано)

Полное описание — в [`docs/database.md`](database.md): ER-диаграммы,
справочник таблиц, перечень ограничений и индексов.

**Ревизия схемы:** `02b0358003e8`. **Таблиц:** 23.

### Что изменилось относительно проектного раздела 5–6

| Проект (этап 1)                          | Реализация (этап 3)                    | Причина                                                                                                                 |
| ---------------------------------------- | -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `product_prices`                         | `price_tiers`                          | Название отражает суть: это ступень, а обычная цена — её частный случай `[1, NULL]`                                     |
| Категории на `ltree` (опционально)       | `VARCHAR path` + `varchar_pattern_ops` | Та же функциональность без нового расширения                                                                            |
| `products.price_mode`                    | `products.pricing_type`                | Единая терминология с `PricingType`                                                                                     |
| `product_media`                          | `product_images`                       | Терминология заказчика                                                                                                  |
| `stock_movements` в перспективе          | Не создан                              | Источником истины по остаткам будет 1С; параллельный регистр создал бы второй источник правды                           |
| Отдельная `regions` не выделялась явно   | Создана                                | Требование «не привязывать архитектуру к Алматы» нуждается в носителе                                                   |
| `refresh_tokens` планировались на этап 4 | Созданы сейчас                         | Относятся к домену пользователей; таблица без логики ничего не стоит, а отдельная миграция на одну таблицу — лишний шаг |
| Атрибуты через таблицы переводов         | JSONB `name_i18n`                      | Справочник читается целиком при отрисовке фильтров; JOIN в самом горячем запросе витрины не оправдан                    |

### Ключевые гарантии на уровне БД

1. **Пересекающиеся ценовые ступени физически невозможны** —
   `EXCLUDE USING gist` на `price_tiers`. Защита действует и для
   Excel-импорта, и для будущего обмена с 1С, где кода приложения
   в цепочке нет.
2. **Заявка переживает удаление товара** — снапшот артикула, названия,
   единицы, цены и типа ценообразования в `request_items`;
   `product_id` со `SET NULL`.
3. **Цена не теряет копейки** — `NUMERIC(14,2)` везде, `float` не
   используется.
4. **Дробные количества поддержаны с первого дня** — `NUMERIC(14,3)`
   в остатках, ступенях и позициях заявок.
5. **Дубли заявок исключены** — уникальный `idempotency_key`.
6. **Поиск не может рассинхронизироваться** — `search_vector` как
   генерируемая колонка PostgreSQL, без триггеров.
7. **Один объект 1С — одна карточка** — частичные уникальные индексы
   по `external_id`.

---

## Приложение В. Аутентификация и RBAC (этап 4, реализовано)

### Схема сессии

```
Вход
  POST /api/v1/admin/auth/login  {email, password}
      ← 200 {access_token, expires_in}          — в память приложения
      ← Set-Cookie: oinau_refresh=...           — httpOnly, Secure, SameSite=strict,
                                                   Path=/api/v1/admin/auth

Работа
  GET /api/v1/admin/...  Authorization: Bearer <access>
      → decode JWT → загрузка пользователя из БД → проверка прав

Обновление (каждые ~15 минут)
  POST /api/v1/admin/auth/refresh   (cookie отправляется браузером)
      старый refresh отзывается, выдаётся новая пара

Выход
  POST /api/v1/admin/auth/logout    отзыв всей цепочки + удаление cookie
```

### Реализованные эндпоинты

| Метод | Путь                                 | Доступ                      |
| ----- | ------------------------------------ | --------------------------- |
| POST  | `/api/v1/admin/auth/login`           | публичный, rate limit по IP |
| POST  | `/api/v1/admin/auth/refresh`         | по refresh-cookie           |
| POST  | `/api/v1/admin/auth/logout`          | по refresh-cookie           |
| GET   | `/api/v1/admin/auth/me`              | access-токен                |
| POST  | `/api/v1/admin/auth/change-password` | access-токен                |
| GET   | `/api/v1/admin/users`                | право `user.manage`         |

### Меры защиты

| Угроза                          | Мера                                                                                            |
| ------------------------------- | ----------------------------------------------------------------------------------------------- |
| Подбор пароля                   | argon2id (64 МБ, 3 прохода), rate limit по IP, блокировка записи после 5 неудач на 15 минут     |
| Перебор email через форму входа | Одинаковый ответ и одинаковое время для неверного пароля и несуществующего адреса               |
| Кража refresh-токена            | Ротация с обнаружением переиспользования: вся цепочка отзывается                                |
| XSS в админке                   | Access — в памяти, refresh — в httpOnly cookie                                                  |
| CSRF                            | Прикладные запросы авторизуются заголовком; refresh-cookie — `SameSite=strict` + узкий `Path`   |
| Подделка токена                 | Фиксированный список алгоритмов (защита от `alg=none`), проверка `iss`/`aud`/`typ`              |
| Утечка дампа БД                 | Пароли — argon2id, refresh-токены — SHA-256, IP — солёный хеш                                   |
| Отложенный отзыв доступа        | Пользователь читается из БД на каждом запросе; смена пароля обесценивает выданные access-токены |

### Модель прав

Роли назначаются, проверяются права: `require_permissions("catalog.write")`,
а не сравнение с ролью. Состав прав описан в
`app/modules/users/permissions.py`.

| Право            | SUPERADMIN | ADMIN | MANAGER | CONTENT_MANAGER | VIEWER |
| ---------------- | :--------: | :---: | :-----: | :-------------: | :----: |
| `catalog.read`   |     ✓      |   ✓   |    ✓    |        ✓        |   ✓    |
| `catalog.write`  |     ✓      |   ✓   |         |        ✓        |        |
| `price.write`    |     ✓      |   ✓   |         |        ✓        |        |
| `stock.write`    |     ✓      |   ✓   |         |        ✓        |        |
| `media.upload`   |     ✓      |   ✓   |         |        ✓        |        |
| `content.write`  |     ✓      |   ✓   |         |        ✓        |        |
| `request.read`   |     ✓      |   ✓   |    ✓    |                 |   ✓    |
| `request.write`  |     ✓      |   ✓   |    ✓    |                 |        |
| `request.export` |     ✓      |   ✓   |    ✓    |                 |        |
| `user.manage`    |     ✓      |   ✓   |         |                 |        |
| `settings.write` |     ✓      |   ✓   |         |                 |        |
| `audit.read`     |     ✓      |   ✓   |         |                 |        |
| `api_key.manage` |     ✓      |       |         |                 |        |

### Слоистость

```
router      валидация входа, HTTP-семантика, cookie
   ↓
service     бизнес-правила, границы транзакции, аудит
   ↓
repository  запросы к БД, отсечение мягко удалённых строк
   ↓
model       схема
```

Разделение нужно, потому что те же операции будут вызываться из фонового
воркера и из будущего обмена с 1С, где HTTP-слоя нет вообще.

---

## Приложение Г. Требования к развёртыванию (безопасность)

Пункты ниже нельзя закрыть кодом приложения — они требуют настройки
инфраструктуры. Без них часть защиты не работает, даже если приложение
собрано правильно.

### Г.1 Обратный прокси и X-Forwarded-For

Приложение по умолчанию **не доверяет** заголовку `X-Forwarded-For`:
`TRUSTED_PROXY_HOPS=0`. Пока прокси не настроен, это правильно —
подделать источник запроса невозможно, но и реальный адрес клиента
приложение не видит.

Чтобы ограничение частоты и аудит работали по адресу клиента, требуется
всё перечисленное одновременно:

1. **Прокси перезаписывает заголовок**, а не дописывает к
   пользовательскому. Для nginx:

   ```nginx
   proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
   proxy_set_header X-Forwarded-Proto $scheme;
   proxy_set_header X-Real-IP $remote_addr;
   ```

   `$proxy_add_x_forwarded_for` дописывает адрес peer-соединения
   в конец цепочки — именно на это рассчитан разбор заголовка
   в `get_client_ip()`.

2. **Приложение доступно только через прокси.** Порт 8000 не должен
   быть открыт наружу, иначе заголовок можно подставить напрямую в обход
   nginx. В Docker Compose для production порт backend не публикуется.

3. **Задано фактическое число прокси:**

   ```
   TRUSTED_PROXY_HOPS=1   # только nginx
   TRUSTED_PROXY_HOPS=2   # Cloudflare + nginx
   ```

   Значение больше реального позволяет клиенту подставить свой адрес;
   меньше реального — приводит к тому, что весь трафик считается
   одним клиентом.

4. **Uvicorn запускается с доверием заголовкам протокола:**
   ```
   uvicorn app.main:app --proxy-headers --forwarded-allow-ips="<IP прокси>"
   ```
   `--forwarded-allow-ips` ограничивает список источников, от которых
   принимаются `X-Forwarded-*`. Значение `*` допустимо только когда
   выполнен пункт 2.

При запуске в production с `TRUSTED_PROXY_HOPS=0` приложение пишет
предупреждение `trusted_proxy_hops_not_configured` в лог.

### Г.2 CORS и cookie

Проверяется при старте, запуск падает при нарушении:

| Параметр          | Требование в production                                                                                        |
| ----------------- | -------------------------------------------------------------------------------------------------------------- |
| `CORS_ORIGINS`    | Непустой список, только `https://`, без `*`. Для проекта: `https://oinau-pro.kz`, `https://admin.oinau-pro.kz` |
| `COOKIE_SECURE`   | Не может быть `false`                                                                                          |
| `COOKIE_SAMESITE` | `strict`; значение `none` требует `COOKIE_SECURE=true`                                                         |
| `SECRET_KEY`      | Не короче 32 символов, не значение по умолчанию                                                                |
| `DEBUG`           | `false`                                                                                                        |

Если API когда-нибудь вынесут на домен, не входящий в `oinau-pro.kz`,
`SameSite=strict` перестанет пропускать refresh-cookie: понадобится
`none` вместе с `Secure`, и защита от CSRF на `/auth/refresh` будет
держаться уже только на узком `Path`.

### Г.3 TLS

`Strict-Transport-Security` приложение выставляет само в production,
но заголовок бессмыслен без действующего сертификата и редиректа
`http → https` на прокси.
