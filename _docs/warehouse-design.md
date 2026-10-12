# Warehouse Packing — Technical Design

**Status:** design, no code yet
**Date:** 2026-10-13
**Inputs:** `_docs/plan.md` (product decisions D1–D34), `_docs/decisions.md` (technical decisions T1–T10, open questions Q1–Q5)
**Repo:** `oinau-pro` monorepo — `apps/backend` (FastAPI + SQLAlchemy 2 async + Alembic), `apps/admin` (Next.js), `apps/web` (Next.js)

---

## 0. Summary

| Area | Design |
|---|---|
| Backend module | New `app/modules/warehouse/` + `app/modules/integration/service_warehouse.py` |
| New tables | `warehouse_documents`, `warehouse_document_lines`, `warehouse_packages` |
| Changed tables | `stocks` (+`reported_at`), `users` (role check allows `WAREHOUSE`) |
| New sequence | `warehouse_document_number_seq` |
| Admin API | `/api/v1/admin/warehouse/*` + `/api/v1/admin/requests/{id}/warehouse` |
| Public API | `GET /api/v1/public/warehouse-packages/{token}` |
| Integration API | `/api/v1/integration/warehouse-documents` (list, ack, write-off, cancel-ack) |
| Same-time packing | Global advisory lock + request row lock + idempotency key + partial unique index |
| Printing | Admin print page (A4 print CSS), QR as SVG in the browser |
| QR page | `apps/web` → `/check/[token]` |

**Hard rule kept:** the site never writes `stocks.quantity` or `stocks.reserved`. The only change to `stocks` is the new `reported_at` timestamp, written by the 1С sync.

---

## 1. Data model

Conventions follow `app/db/base.py` and `app/db/types.py`:
- `IntPkMixin` (BIGINT identity), `PublicUuidMixin` (`gen_random_uuid()`), `TimestampMixin`
- `qty_type()` = `NUMERIC(14,3)`; all times `TIMESTAMPTZ`
- statuses are `VARCHAR(32)` + `enum_check(...)`, never a PostgreSQL ENUM
- constraint and index names follow the project's naming convention (`uq_…`, `ix_…`, `ck_…`, `fk_…`)

Documents are **never deleted** (cancel instead), so there is no `SoftDeleteMixin`.

### 1.1 `warehouse_documents` — the summary document (the only write-off document)

Model: `WarehouseDocument(Base, IntPkMixin, PublicUuidMixin, TimestampMixin)` in `app/modules/warehouse/models.py`.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | BIGINT identity | no | | PK |
| `uuid` | UUID | no | `gen_random_uuid()` | Identifier for 1С (integration API). Unique. |
| `number` | VARCHAR(24) | no | | `WH-2026-000123`. From `warehouse_document_number_seq`. Never reused. |
| `request_id` | BIGINT FK → `requests.id` ON DELETE RESTRICT | no | | |
| `warehouse_id` | BIGINT FK → `warehouses.id` ON DELETE RESTRICT | no | | Version 1: the single active warehouse (see §1.6) |
| `status` | VARCHAR(32) | no | `'CREATED'` | `CREATED`, `PACKED`, `CANCELLED` (`WarehouseDocumentStatus`) |
| `package_count` | SMALLINT | no | | Total packages, used for "3/5" |
| `stock_checked_at` | TIMESTAMPTZ | no | | When availability was calculated (D29) |
| `stock_data_as_of` | TIMESTAMPTZ | yes | | Oldest stock data time among the lines (for the 24-hour warning on print) |
| `idempotency_key` | VARCHAR(64) | yes | | From the admin client on create |
| `request_hash` | VARCHAR(64) | yes | | SHA-256 of the normalized create body (to detect the same key reused with a different body) |
| `created_by_id` | BIGINT FK → `users.id` ON DELETE SET NULL | yes | | |
| `packed_at` | TIMESTAMPTZ | yes | | |
| `packed_by_id` | BIGINT FK → `users.id` ON DELETE SET NULL | yes | | |
| `cancelled_at` | TIMESTAMPTZ | yes | | |
| `cancelled_by_id` | BIGINT FK → `users.id` ON DELETE SET NULL | yes | | |
| `cancel_reason` | TEXT | yes | | Required by the service on cancel (assumption, Q4) |
| `external_id` | VARCHAR(64) | yes | | 1С document number/GUID, sent with `ack`. Kept after the first ack. |
| `exported_at` | TIMESTAMPTZ | yes | | 1С read the packed document (`ack`) |
| `write_off_confirmed_at` | TIMESTAMPTZ | yes | | 1С finished the write-off |
| `cancel_exported_at` | TIMESTAMPTZ | yes | | 1С read the cancellation |
| `created_at`, `updated_at` | TIMESTAMPTZ | no | `now()` | `TimestampMixin` |

**Check constraints**
- `ck_warehouse_documents_status` — `enum_check("status", WarehouseDocumentStatus, "status")`
- `ck_warehouse_documents_package_count_positive` — `package_count > 0`
- `ck_warehouse_documents_packed_has_time` — `status <> 'PACKED' OR packed_at IS NOT NULL`
- `ck_warehouse_documents_cancelled_iff_time` — `(status = 'CANCELLED') = (cancelled_at IS NOT NULL)`
- `ck_warehouse_documents_export_after_pack` — `exported_at IS NULL OR packed_at IS NOT NULL` (1С never sees a document that wasn't packed — D21)
- `ck_warehouse_documents_write_off_after_export` — `write_off_confirmed_at IS NULL OR exported_at IS NOT NULL`
- `ck_warehouse_documents_cancel_export_valid` — `cancel_exported_at IS NULL OR (status = 'CANCELLED' AND exported_at IS NOT NULL)`

**Indexes**
- `uq_warehouse_documents_number` UNIQUE (`number`)
- `uq_warehouse_documents_active_request` UNIQUE (`request_id`) WHERE `status IN ('CREATED','PACKED')` — **T3**: at most one active document per request
- `uq_warehouse_documents_idempotency_key` UNIQUE (`idempotency_key`) WHERE `idempotency_key IS NOT NULL`
- `uq_warehouse_documents_external_id` UNIQUE (`external_id`) WHERE `external_id IS NOT NULL`
- `ix_warehouse_documents_request_id` (`request_id`) — document history of a request, including cancelled ones
- `ix_warehouse_documents_status_created` (`status`, `created_at DESC`) — admin document list
- `ix_warehouse_documents_onec_write_off_pending` (`packed_at`) WHERE `status = 'PACKED' AND exported_at IS NULL` — 1С pull
- `ix_warehouse_documents_onec_cancel_pending` (`cancelled_at`) WHERE `status = 'CANCELLED' AND exported_at IS NOT NULL AND cancel_exported_at IS NULL` — 1С pull

### 1.2 `warehouse_document_lines` — one line per request line

Model: `WarehouseDocumentLine(Base, IntPkMixin)`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | BIGINT identity | no | PK |
| `document_id` | BIGINT FK → `warehouse_documents.id` ON DELETE CASCADE | no | |
| `request_item_id` | BIGINT FK → `request_items.id` ON DELETE RESTRICT | no | |
| `product_id` | BIGINT FK → `products.id` ON DELETE RESTRICT | no | Must be set; unlinked request items block packing (§3.3) |
| `sku_snapshot` | VARCHAR(64) | no | Copied from `request_items.sku_snapshot` (ADR-0005) |
| `name_snapshot` | VARCHAR(500) | no | Copied from `request_items.name_snapshot` |
| `unit_snapshot` | VARCHAR(16) | no | Copied from `request_items.unit_snapshot` |
| `color_name_snapshot` | VARCHAR(255) | yes | Copied from `request_items.color_name_snapshot`; matters for picking |
| `quantity` | NUMERIC(14,3) | no | Equals `request_items.quantity` (D9: the whole request) |
| `available_at_check` | NUMERIC(14,3) | no | Availability for this product at `stock_checked_at`, **before** this document. Can be negative if `reserved > quantity`. |
| `sort_order` | INTEGER | no | Copied from `request_items.sort_order` |

There are **no prices** in this table (D29).

**Constraints / indexes**
- `ck_warehouse_document_lines_quantity_positive` — `quantity > 0`
- `uq_warehouse_document_lines_document_item` UNIQUE (`document_id`, `request_item_id`)
- `ix_warehouse_document_lines_product_id` (`product_id`) — used by the availability query (§4)

### 1.3 `warehouse_packages` — one row per box, one SKU per box (D11)

Model: `WarehousePackage(Base, IntPkMixin, PublicUuidMixin)`. The `uuid` is the **QR token** (122 random bits; can't be guessed — D31).

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | BIGINT identity | no | PK |
| `uuid` | UUID | no | QR token, unique |
| `document_id` | BIGINT FK → `warehouse_documents.id` ON DELETE CASCADE | no | |
| `line_id` | BIGINT FK → `warehouse_document_lines.id` ON DELETE CASCADE | no | The single SKU in this box |
| `seq` | SMALLINT | no | 1…N within the document; the label is `{number}-{seq}/{package_count}` |
| `quantity` | NUMERIC(14,3) | no | Decimals allowed (D12) |

The label `WH-2026-000123-3/5` is **calculated, not stored**, so it can't drift from the document.

**Constraints / indexes**
- `ck_warehouse_packages_quantity_positive` — `quantity > 0`
- `ck_warehouse_packages_seq_positive` — `seq >= 1`
- `uq_warehouse_packages_document_seq` UNIQUE (`document_id`, `seq`)
- `ix_warehouse_packages_line_id` (`line_id`)
- (`uuid` unique comes from `PublicUuidMixin`)

**Rule "sum of packages = line quantity" (D13)** is enforced in `WarehouseService` before insert and covered by tests. A database trigger was rejected: the project deliberately avoids triggers (`search_vector` is a generated column for the same reason).

### 1.4 Change to `stocks` (T7)

| Column | Type | Null | Notes |
|---|---|---|---|
| `reported_at` | TIMESTAMPTZ | yes | Last time 1С **mentioned** this row in an `inventory/bulk-upsert`, even if the numbers didn't change. Set with the site's clock, so there's no clock difference between 1С and the site. |

- `synced_at` keeps its meaning ("when the data really changed").
- No audit record is written when only `reported_at` changes.

### 1.5 Change to `users`

- The role check constraint (`enum_check("role", UserRole, "role")` → `ck_users_role`) is recreated to allow `WAREHOUSE`.

### 1.6 Sequence and numbering (D32)

- `CREATE SEQUENCE warehouse_document_number_seq` — separate from `warehouse_documents.id`. Gaps are allowed (a rolled-back transaction uses up a number); numbers are never reused.
- Format: `WH-{year}-{nextval:06d}`, built by `build_document_number(value, moment)` in `app/modules/warehouse/service.py`, mirroring `build_request_number` in `app/modules/requests/service.py`.
- The year comes from `now()` in `Asia/Almaty`. (Requests use the moment's year; we keep the same behaviour and note it in §11.)
- The sequence doesn't reset each year. `WH-2027-000124` follows `WH-2026-000123`. That's acceptable and simpler, and the numbers stay unique.

**Warehouse choice in version 1 (D33):** `WarehouseService` uses the single active `warehouses` row. If there are zero or several active warehouses, packing fails with `warehouse_not_configured` (409). This is a deliberate guard, not a selection UI.

### 1.7 Enums (`app/modules/warehouse/enums.py`)

- `WarehouseDocumentStatus` — `CREATED`, `PACKED`, `CANCELLED`
- `OneCState` (calculated, never stored) — `NOT_SENT`, `WAITING_FOR_1C`, `READ_BY_1C`, `WRITE_OFF_CONFIRMED`, `CANCEL_PENDING`, `CANCEL_READ`
- `PackageCheckStatus` (public page) — `VALID`, `CANCELLED`

### 1.8 Alembic migration plan

One revision: `apps/backend/alembic/versions/2026_10_xx_xxxx-<rev>_warehouse_packing.py`
`down_revision = "e7a2b9c4d150"` (`product_colors`, the current head — check again before generating).

**Upgrade order**
1. `users`: drop `ck_users_role`, recreate it with `WAREHOUSE` added.
2. `stocks`: add `reported_at TIMESTAMPTZ NULL`. Backfill: `UPDATE stocks SET reported_at = synced_at WHERE sync_source = '1c'`.
3. `CREATE SEQUENCE warehouse_document_number_seq START 1`.
4. Create `warehouse_documents` with checks and indexes (including the partial unique ones).
5. Create `warehouse_document_lines`.
6. Create `warehouse_packages`.

**Downgrade order** — the reverse.
- Before recreating the old `ck_users_role`, the downgrade **fails with a clear message** if any user has role `WAREHOUSE`. It doesn't silently change those users.
- Dropping the tables loses documents. That's acceptable for a downgrade, but it's written in the migration's docstring.

**Process**
- Generated with `make makemigration m="warehouse packing"`, then reviewed by hand (partial indexes and checks need care).
- Checked in CI by `alembic upgrade head` followed by `alembic check` (metadata matches migrations). The new models must be imported in the list at the bottom of `app/db/base.py`, or `alembic check` does not see them.
- Not run on container start (project rule 8). In production: `make prod-backup` → `make prod-migrate`.

---

## 2. State machines

### 2.1 Warehouse status (`warehouse_documents.status`)

```
          create split                 confirm packed
 (none) ───────────────► CREATED ─────────────────────► PACKED
                            │                              │
                            │ cancel                       │ cancel
                            ▼                              ▼
                        CANCELLED  ◄───────────────────────┘
```

| Transition | Trigger | Who (permission) | Preconditions | Side effects |
|---|---|---|---|---|
| — → `CREATED` | `POST /admin/warehouse/requests/{id}/documents` | `warehouse.pack` (WAREHOUSE, MANAGER, ADMIN, SUPERADMIN) | Request is `kind=CART`, `status=APPROVED`, not deleted; no active document; split is valid; enough stock for every line | Inserts document, lines and packages; writes stock check time; audit `warehouse.document_created` |
| `CREATED` → `PACKED` | `POST /admin/warehouse/documents/{id}/pack` | `warehouse.pack` | Status is `CREATED` | `packed_at`, `packed_by_id`; the document becomes visible to 1С; audit `warehouse.document_packed` |
| `CREATED` → `CANCELLED` | `POST /admin/warehouse/documents/{id}/cancel` | `warehouse.cancel` | Reason given | `cancelled_*`; 1С is never involved (D21); the request unlocks; audit |
| `PACKED` → `CANCELLED` | same | `warehouse.cancel` | Reason given | `cancelled_*`; if `exported_at` is set, the document appears in the 1С cancellation list; the request unlocks; audit |
| `PACKED` → `PACKED`, `CANCELLED` → `CANCELLED` | repeating the same call | | | Nothing changes, returns 200 with the current state (safe after a network retry, the same as `update_status`) |
| anything else | | | | 409 `warehouse_invalid_transition` |

No partial packing: "Packed" applies to the whole document and all its packages at once (assumption from plan open question 2).

### 2.2 1С status (calculated from timestamps — T2)

| `OneCState` | Condition |
|---|---|
| `NOT_SENT` | `status = CREATED`, **or** `status = CANCELLED AND exported_at IS NULL` |
| `WAITING_FOR_1C` | `status = PACKED AND exported_at IS NULL` |
| `READ_BY_1C` | `status = PACKED AND exported_at IS NOT NULL AND write_off_confirmed_at IS NULL` |
| `WRITE_OFF_CONFIRMED` | `status = PACKED AND write_off_confirmed_at IS NOT NULL` |
| `CANCEL_PENDING` | `status = CANCELLED AND exported_at IS NOT NULL AND cancel_exported_at IS NULL` |
| `CANCEL_READ` | `status = CANCELLED AND cancel_exported_at IS NOT NULL` |

| 1С action | Endpoint | Scope | Allowed when | Effect |
|---|---|---|---|---|
| Read the packed document | `POST /integration/warehouse-documents/{uuid}/ack` | `warehouse:read` | `packed_at IS NOT NULL`. This also accepts a document cancelled **after** it was listed: 1С then finds it in the cancellation list. | Sets `exported_at` (+`external_id`) once; a repeat returns the stored values |
| Confirm write-off | `POST …/{uuid}/write-off` | `warehouse:write` | `exported_at IS NOT NULL` | Sets `write_off_confirmed_at` once; a repeat changes nothing |
| Confirm cancellation read | `POST …/{uuid}/cancel-ack` | `warehouse:write` | `status = CANCELLED AND exported_at IS NOT NULL` | Sets `cancel_exported_at` once |

A write-off confirmation is accepted for a document that is already `CANCELLED` (1С wrote off before it saw the cancellation). 1С then reverses the write-off itself (D22).

### 2.3 Effect on the request (D15, D17, D19)

Guard added to `AdminRequestService.update_status` (`app/modules/requests/service_admin.py`). The request row is already locked there with `get_for_update`.

| Request has an active document | Target status | Result |
|---|---|---|
| `CREATED` | anything but `APPROVED` | 409 `request_locked_by_warehouse` |
| `PACKED` | `COMPLETED` | allowed (D19: the manager closes after delivery) |
| `PACKED` | anything else | 409 `request_locked_by_warehouse` |
| none | anything | unchanged behaviour |

Request items have no edit endpoint in the admin API today. If one is added later, it must use the same guard.

---

## 3. API

Error format: `{"error": {"code", "message", "details"}}` (`app/core/exceptions.py`). New errors live in `app/modules/warehouse/exceptions.py`, based on `AppError` / `ConflictError` / `NotFoundError`. All quantities go out and come in as **strings** (project rule 5). Types for the frontend come from `make gen-types`.

### 3.1 Admin API — `app/modules/warehouse/router_admin.py`, included in `app/api/v1/admin.py`

All endpoints: JWT + `require_permissions(...)`, no caching. Changes are written to `audit_log` via `AuditService` with actions in `app/modules/warehouse/audit.py`.

**Response schemas** (`app/modules/warehouse/schemas_admin.py`) contain **no** price fields (`unit_price_snapshot`, `line_total_snapshot`, `total_estimate`) and **no** contact fields (`customer_name`, `phone`, `email`, `company`, `bin`, `city`, `comment`). Tests check that these keys are absent.

#### A1. `GET /api/v1/admin/warehouse/queue` — requests ready to pack
- **Permission:** `warehouse.read`
- **Query:** `page`, `page_size` (`PageParams` from `app/core/pagination.py`), `search` (request number)
- **Response 200:** `Page[PackingQueueItem]` — `request_id`, `request_number`, `approved_at` (from `request_status_history`), `line_count`, `has_unlinked_items: bool`
- **Selection:** `kind = CART`, `status = APPROVED`, `deleted_at IS NULL`, no active document. Ordered by `approved_at`, oldest first.

#### A2. `GET /api/v1/admin/warehouse/requests/{request_id}/packing` — data for the split screen
- **Permission:** `warehouse.read`
- **Response 200:** `PackingView`
  - `request_id`, `request_number`, `request_status`
  - `lines[]`: `request_item_id`, `product_id | null`, `sku`, `name`, `color_name`, `unit`, `needed`, `available | null`, `shortage` (`max(0, needed − available)`), `data_as_of`, `is_linked`
  - `checked_at`, `data_as_of` (oldest line), `data_stale: bool` (older than `WAREHOUSE_STOCK_STALE_HOURS`, default 24 — D27)
  - `can_pack: bool` plus `blockers[]` codes (`request_not_approved`, `request_item_unlinked`, `insufficient_stock`, `active_document_exists`)
  - `active_document: WarehouseDocumentSummary | null`
- **Errors:** 404 `request_not_found` (also for `kind = GENERAL`)

#### A3. `POST /api/v1/admin/warehouse/requests/{request_id}/documents` — create the split
- **Permission:** `warehouse.pack`
- **Body `CreateSplit`:**
  ```
  idempotency_key: str (UUID from the client, required)
  lines: [ { request_item_id: int, packages: [ "100", "100", "50.5", ... ] } ]
  ```
  Package amounts are decimal strings > 0, at most 3 decimal places. Limit: `WAREHOUSE_MAX_PACKAGES` (default 200) per document.
- **Response 201:** `WarehouseDocumentRead` (see A5). A repeat with the same key and the same body returns **200** with the existing document.
- **Errors:**

| Code | HTTP | When | `details` |
|---|---|---|---|
| `request_not_found` | 404 | No such request, or deleted, or not `CART` | |
| `request_not_approved` | 409 | Status isn't `APPROVED` (D15) | `status` |
| `active_document_exists` | 409 | An active document already exists (also mapped from `uq_warehouse_documents_active_request` via `app/core/integrity.py`) | `document_id`, `number` |
| `split_lines_mismatch` | 422 | The body lines aren't exactly the request lines (missing / extra / duplicate) | `missing[]`, `unexpected[]` |
| `split_sum_mismatch` | 422 | For some line, the sum of packages ≠ the line quantity (D13) | `lines[]: {request_item_id, needed, packed}` |
| `request_item_unlinked` | 422 | A request line has `product_id = NULL` (open question 3 in the plan, assumed: block) | `request_item_ids[]` |
| `insufficient_stock` | 409 | Available < needed for any line (D16) | `lines[]: {request_item_id, sku, needed, available, shortage}`, `checked_at` |
| `too_many_packages` | 422 | More than `WAREHOUSE_MAX_PACKAGES` | `limit` |
| `idempotency_key_conflict` | 409 | Same key, different body (`request_hash` differs) | |
| `warehouse_not_configured` | 409 | Not exactly one active warehouse | |
| `validation_error` | 422 | Pydantic (bad decimal, ≤ 0, empty list) | |

#### A4. `GET /api/v1/admin/warehouse/documents` — document list
- **Permission:** `warehouse.read`
- **Query:** `page`, `page_size`, `status`, `onec_state`, `search` (document or request number), `created_from`, `created_to`
- **Response 200:** `Page[WarehouseDocumentSummary]` — `id`, `number`, `request_id`, `request_number`, `status`, `onec_state`, `package_count`, `created_at`, `packed_at`, `cancelled_at`

#### A5. `GET /api/v1/admin/warehouse/documents/{document_id}` — detail (also feeds the print page)
- **Permission:** `warehouse.read`
- **Response 200:** `WarehouseDocumentRead`
  - The summary fields above, plus:
  - `warehouse: {code, name}`
  - `stock_checked_at`, `stock_data_as_of`, `data_stale_at_check: bool`
  - `created_by`, `packed_by`, `cancelled_by` (`{id, full_name}`), `cancel_reason`
  - 1С timestamps: `exported_at`, `write_off_confirmed_at`, `cancel_exported_at`, `external_id`
  - `lines[]`: `id`, `sku`, `name`, `color_name`, `unit`, `quantity`, `available_at_check`, `package_seqs[]`
  - `packages[]`: `seq`, `label` (`WH-…-3/5`), `line_id`, `sku`, `name`, `color_name`, `unit`, `quantity`, `check_url` (`{PUBLIC_SITE_URL}/check/{uuid}` — built on the backend, so the admin app doesn't hard-code the site address)
- **Errors:** 404 `warehouse_document_not_found`

#### A6. `POST /api/v1/admin/warehouse/documents/{document_id}/pack`
- **Permission:** `warehouse.pack`
- **Body:** none
- **Response 200:** `WarehouseDocumentRead`
- **Errors:** 404; 409 `warehouse_invalid_transition` (status is `CANCELLED`). Already `PACKED` → 200, no change.

#### A7. `POST /api/v1/admin/warehouse/documents/{document_id}/cancel`
- **Permission:** `warehouse.cancel`
- **Body:** `{ reason: str (1..1000) }`
- **Response 200:** `WarehouseDocumentRead`
- **Errors:** 404; 422 `validation_error` (empty reason). Already `CANCELLED` → 200, no change.

#### A8. `GET /api/v1/admin/requests/{request_id}/warehouse` — manager view on the request page (D26)
- Lives in `app/modules/warehouse/router_admin.py`, path under `/admin/requests` (registered after `requests_router`).
- **Permission:** `request.read` (managers don't need `warehouse.read` to see availability)
- **Response 200:** `RequestWarehouseInfo`
  - `lines[]` (`request_item_id`, `needed`, `available`, `shortage`, `data_as_of`, `is_linked`)
  - `checked_at`, `data_stale`
  - `documents[]: WarehouseDocumentSummary` (including cancelled ones, newest first)

### 3.2 Public API — `app/modules/warehouse/router_public.py`, included in `app/api/v1/public.py`

#### P1. `GET /api/v1/public/warehouse-packages/{token}`
- **Auth:** none.
- **Rate limit:** `rate_limit("package_check", "RATE_LIMIT_PACKAGE_CHECK")`, new setting, default `60/minute` per IP.
- **Headers:** `Cache-Control: no-store` (a package can become cancelled), `X-Robots-Tag: noindex`.
- **Response 200 `PackageCheck`** (`schemas_public.py`):
  ```
  label: "WH-2026-000123-3/5"
  document_number: "WH-2026-000123"
  seq: 3, total: 5
  request_number: "R-2026-000142"
  sku, name, color_name | null, unit, quantity: "100.000"
  status: "VALID" | "CANCELLED"
  ```
  `VALID` means the document is `CREATED` or `PACKED`. No prices, client name, contacts, warehouse or users (D30, D31).
- **Errors:** 404 `package_not_found`. The same response for an unknown token and for a malformed (non-UUID) token, so the API doesn't reveal which one it was. 429 when the rate limit is hit.

### 3.3 Integration API (1С) — routes in `app/api/v1/integration.py`, logic in `app/modules/integration/service_warehouse.py`

These use the same authentication chain as the existing endpoints: `ONE_C_INTEGRATION_ENABLED` → IP allowlist → `X-API-Key` → scope → rate limit per key (`docs/integrations.md` §3.2).

New scopes in `IntegrationScope` (`app/modules/integration/security.py`):
- `WAREHOUSE_READ = "warehouse:read"`
- `WAREHOUSE_WRITE = "warehouse:write"`

Both are added to `ALL`. `app/scripts/create_api_key.py` accepts them.

Every call writes a `sync_log` row (direction `outbound`/`inbound`, entity `warehouse_document`). Document changes are written to `audit_log` with `actor="1c"`, the same way stock sync does it.

#### I1. `GET /api/v1/integration/warehouse-documents`
- **Scope:** `warehouse:read`
- **Query:** `limit` (1..200, default 200), `include_done: bool = false` (for investigating incidents, like `include_exported` for requests)
- **Response 200 `IntegrationWarehouseDocumentPage`:** `{ items: [...], total }`. Pending items in event order:
  - `event = "write_off"` — `status = PACKED AND exported_at IS NULL`, ordered by `packed_at`
  - `event = "cancel"` — `status = CANCELLED AND exported_at IS NOT NULL AND cancel_exported_at IS NULL`, ordered by `cancelled_at`
- **Item:**
  ```
  uuid, number, event, status,
  request: { uuid, number, external_id | null },
  warehouse: { code, external_id | null },
  packed_at, cancelled_at | null, cancel_reason | null,
  stock_checked_at,
  lines: [ { product_external_id | null, sku, name, unit, quantity } ],   ← the write-off basis
  packages: [ { seq, label, sku, quantity } ]                              ← packing details only, never written off (D8)
  ```
  The schema states it in `description`: "only `lines` are written off; `packages` are informational".

#### I2. `POST /api/v1/integration/warehouse-documents/{uuid}/ack`
- **Scope:** `warehouse:read` (the same split as `requests:read` + request ack)
- **Body:** `{ external_id?: str (≤ 64) }`
- **Response 200 `WarehouseAckResult`:** `{ uuid, external_id, exported_at, status }`. `status` lets 1С see that a document was cancelled between list and ack.
- **Errors:** 404 `warehouse_document_not_found` (unknown or never packed — a `CREATED` document is invisible to 1С); 409 `external_id_conflict` (the external_id is already used by another document). A repeat returns the stored values and doesn't overwrite `external_id`.

#### I3. `POST /api/v1/integration/warehouse-documents/{uuid}/write-off`
- **Scope:** `warehouse:write`
- **Body:** `{ external_id?: str }` (optional; used only if ack didn't set it)
- **Response 200:** `{ uuid, write_off_confirmed_at, status }`
- **Errors:** 404; 409 `warehouse_not_acknowledged` (`exported_at IS NULL`). A repeat changes nothing.

#### I4. `POST /api/v1/integration/warehouse-documents/{uuid}/cancel-ack`
- **Scope:** `warehouse:write`
- **Body:** none
- **Response 200:** `{ uuid, cancel_exported_at }`
- **Errors:** 404; 409 `warehouse_not_cancelled` (status isn't `CANCELLED`); 409 `warehouse_not_acknowledged` (1С never read it, so there's nothing to cancel on its side). A repeat changes nothing.

#### I5. Change to `POST /api/v1/integration/inventory/bulk-upsert` (T7)
- `StockSyncService._apply_stock` sets `stock.reported_at = now` for **every** matched row, including the "nothing changed" branch. It still doesn't touch `synced_at` or write an audit record in that branch.
- The response contract is unchanged.
- `docs/integrations.md` §3.6 gets one paragraph explaining `reported_at` and why a full snapshot is preferred (Q2).

### 3.4 Settings (`app/core/config.py`, `.env.example`, `.env.production.example`)

| Setting | Default | Use |
|---|---|---|
| `WAREHOUSE_STOCK_STALE_HOURS` | `24` | D27 warning |
| `WAREHOUSE_MAX_PACKAGES` | `200` | A3 limit |
| `RATE_LIMIT_PACKAGE_CHECK` | `60/minute` | P1 |

`PUBLIC_SITE_URL` (already exists) is used for `check_url`.

---

## 4. "Available stock" formula (D23, D25, T10)

For product `p` in the active warehouse `w`:

```
available(p) = quantity(p, w) − reserved(p, w) − pending(p)

pending(p) = Σ line.quantity
             over warehouse_document_lines line
             join warehouse_documents d on d.id = line.document_id
             where line.product_id = p
               and d.warehouse_id = w
               and d.status in ('CREATED', 'PACKED')
               and not (                                   -- not yet reflected in 1С's number
                     d.write_off_confirmed_at is not null
                 and s.reported_at is not null
                 and s.reported_at > d.write_off_confirmed_at
               )
```

Where `s` is the `stocks` row for (`p`, `w`). If no `stocks` row exists, `quantity = reserved = 0` and `s.reported_at` is `NULL`.

**SQL (one query for all products of a request):**

```sql
SELECT
  ri.id                                         AS request_item_id,
  ri.product_id,
  COALESCE(s.quantity, 0) - COALESCE(s.reserved, 0)
    - COALESCE(pend.qty, 0)                     AS available,
  COALESCE(s.reported_at, s.synced_at, s.updated_at) AS data_as_of
FROM request_items ri
LEFT JOIN stocks s
       ON s.product_id = ri.product_id AND s.warehouse_id = :warehouse_id
LEFT JOIN LATERAL (
  SELECT SUM(l.quantity) AS qty
  FROM warehouse_document_lines l
  JOIN warehouse_documents d ON d.id = l.document_id
  WHERE l.product_id = ri.product_id
    AND d.warehouse_id = :warehouse_id
    AND d.status IN ('CREATED', 'PACKED')
    AND NOT (d.write_off_confirmed_at IS NOT NULL
             AND s.reported_at IS NOT NULL
             AND s.reported_at > d.write_off_confirmed_at)
) pend ON TRUE
WHERE ri.request_id = :request_id;
```

**Notes**
- On the request page and the packing screen, the request's own active document is **not** excluded. Once a request is packed, its "available" shows what's left for others, and A2 shows the document instead of a split form.
- During A3 there's no active document for this request yet (that would be an error), so nothing needs excluding.
- `data_as_of` uses `reported_at` first, then `synced_at` for older rows, then `updated_at` for stock entered by hand or by Excel.
- `data_stale = min(data_as_of) < now − WAREHOUSE_STOCK_STALE_HOURS`. A missing stock row counts as stale.
- The calculation lives **only** in `app/modules/warehouse/availability.py` (backend rule 4). The frontend shows numbers, it never calculates them.
- Cancelling a document after a write-off stops subtracting immediately, while 1С's number stays lower until 1С pushes the reversal. Availability is **too low** for that window, which is safe.

---

## 5. Concurrency (T9)

### 5.1 Creating a split (A3) — one transaction in `WarehouseService.create_document`

1. **Idempotency first (no lock):** look up `idempotency_key`. Found with the same `request_hash` → return the existing document (200). Found with a different hash → 409 `idempotency_key_conflict`.
2. **`SELECT pg_advisory_xact_lock(WAREHOUSE_PACKING_LOCK_KEY)`** — a constant in `app/modules/warehouse/repository.py` (e.g. `7_246_915_002`, next to `CATALOG_IMPORT_LOCK_KEY = 7_246_915_001`), documented the same way. All packings wait for each other; the lock is released at commit or rollback.
3. **`AdminRequestRepository.get_for_update(request_id)`** — locks the request row, so `update_status` can't change the status at the same moment.
4. Validate: request kind and status, no active document, lines match, sums match, every item linked, the warehouse is configured.
5. Calculate availability (§4) **inside the lock**; block on any shortage.
6. `nextval('warehouse_document_number_seq')`; insert the document, lines and packages; audit; commit.
7. **Final guards:** the unique indexes `uq_warehouse_documents_active_request` and `uq_warehouse_documents_idempotency_key` are mapped by `app/core/integrity.py` to `active_document_exists` / a re-read by key.

**Why there are no deadlocks**
- Packing takes the advisory lock, then the request row.
- `update_status` takes only the request row and reads documents.
- The 1С stock upsert takes only `stocks` rows.
- No path takes these locks in the opposite order.

**What happens if a 1С push lands during packing:** with READ COMMITTED, step 5 reads the latest committed `stocks` row. A push that commits afterwards changes `quantity` and `reported_at` in the same row update, so the formula never sees a half-applied change.

### 5.2 Pack / cancel (A6, A7) and 1С callbacks (I2–I4)

- Each one locks the **document row** (`SELECT … FOR UPDATE`) before reading its status, so "cancel" and "1С ack" for the same document run one after the other.
- Cancel doesn't take the packing lock, because it only **increases** availability.
- Cancel also locks the request row (status-guard consistency).

### 5.3 Double click / retry

- **Create:** the client generates `idempotency_key` when the split screen opens (like the public request form) and reuses it on retry.
- **Pack / cancel / 1С callbacks:** a repeat changes nothing (§2).

---

## 6. Warehouse role and permissions (T8)

### 6.1 Backend — `app/modules/users/enums.py` and `app/modules/users/permissions.py`

- `UserRole.WAREHOUSE = "WAREHOUSE"`
- New permission constants: `WAREHOUSE_READ = "warehouse.read"`, `WAREHOUSE_PACK = "warehouse.pack"`, `WAREHOUSE_CANCEL = "warehouse.cancel"`
- `_WAREHOUSE = frozenset({WAREHOUSE_READ, WAREHOUSE_PACK, WAREHOUSE_CANCEL})`
- `_MANAGER` adds the three (backup packer — D14)
- `_ADMIN` gets them through `_MANAGER`
- `VIEWER` and `CONTENT_MANAGER` don't get them

| Permission | SUPERADMIN | ADMIN | MANAGER | WAREHOUSE | CONTENT_MANAGER | VIEWER |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| `warehouse.read` | ✓ | ✓ | ✓ | ✓ | | |
| `warehouse.pack` | ✓ | ✓ | ✓ | ✓ | | |
| `warehouse.cancel` | ✓ | ✓ | ✓ | ✓ *(assumption, Q4)* | | |
| `request.read` | ✓ | ✓ | ✓ | **no** | | ✓ |
| `catalog.read` | ✓ | ✓ | ✓ | **no** | ✓ | ✓ |

WAREHOUSE has no `request.read` and no `catalog.read`. Everything it needs comes from `/admin/warehouse/*` schemas that leave out prices and contacts.

### 6.2 Endpoint access

| Endpoint | Permission | WAREHOUSE | MANAGER |
|---|---|:-:|:-:|
| A1 queue | `warehouse.read` | ✓ | ✓ |
| A2 packing view | `warehouse.read` | ✓ | ✓ |
| A3 create split | `warehouse.pack` | ✓ | ✓ |
| A4 / A5 documents | `warehouse.read` | ✓ | ✓ |
| A6 pack | `warehouse.pack` | ✓ | ✓ |
| A7 cancel | `warehouse.cancel` | ✓ | ✓ |
| A8 request warehouse info | `request.read` | ✗ | ✓ |
| `/admin/requests/*` (existing) | `request.*` | ✗ (403) | ✓ |
| `/admin/stock`, products, etc. | `catalog.*` / `stock.*` | ✗ (403) | read only |
| `/admin/users` | `user.manage` | ✗ | ✗ |

### 6.3 Admin screens

| Screen | Route | Visible with | WAREHOUSE | MANAGER |
|---|---|---|:-:|:-:|
| Packing queue + documents | `/packing` | `warehouse.read` | ✓ | ✓ |
| Split editor | `/packing/requests/[requestId]` | `warehouse.read` (save needs `warehouse.pack`) | ✓ | ✓ |
| Document detail | `/packing/documents/[id]` | `warehouse.read` (buttons need `pack` / `cancel`) | ✓ | ✓ |
| Print page | `/print/warehouse-documents/[id]` | `warehouse.read` | ✓ | ✓ |
| Request detail — warehouse block | `/requests/[id]` | `request.read` | ✗ | ✓ |
| Dashboard `/` | — | (existing) | sees only cards it has permissions for | |

`apps/admin/src/lib/auth/permissions.ts` gets the three permission codes, their `PERMISSION_LABELS`, and `ROLE_LABELS.WAREHOUSE = 'Кладовщик'`. `apps/admin/src/lib/users.ts` gets `ROLE_HINTS.WAREHOUSE`. Both role maps are typed `Record<UserRole, string>`, and `UserRole` comes from the generated types (`make gen-types`), so the label and the hint must be added in the same change that adds the role, or the admin app does not typecheck. The role options in the user management screen are built from `ROLE_LABELS`.

---

## 7. QR code and printing (T5)

### 7.1 QR code
- **Content:** only `check_url` = `{PUBLIC_SITE_URL}/check/{package.uuid}` (≈ 70 characters). No data inside the QR itself, so a cancelled box can't show "valid" from stale printed data.
- **Generation:** in the admin app, a new dependency in `apps/admin/package.json`. The candidate is the `qrcode` npm package (MIT), rendering to an SVG string; the exact version is pinned in the PR. Error correction level **M**. Printed size about **40 × 40 mm** with a 4-module quiet zone. The short URL is printed as text under the code, in case scanning fails.
- **Component:** `apps/admin/src/components/warehouse/QrCode.tsx`, which takes `value` and `sizeMm` and renders inline `<svg>` (vector, so it's sharp on any printer).

### 7.2 Print page
- **Route** `apps/admin/src/app/print/warehouse-documents/[id]/page.tsx`. It sits **outside** the `(panel)` route group, so the sidebar and header aren't printed. It's wrapped in `RequirePermission` (`warehouse.read`) from `components/session/AuthGate.tsx`.
- **Data:** A5 (`GET /admin/warehouse/documents/{id}`).
- **CSS** `components/warehouse/Print.module.css`:
  - `@page { size: A4; margin: 12mm; }`
  - each sheet `break-after: page`
  - black and white, no backgrounds; the "Print" button is hidden with `@media print`
- **Page 1 — summary (stays at the warehouse, D7), no prices:**
  - Header: `WH-2026-000123`, date, warehouse name, request `R-2026-000142`
  - Stock check line: "Остатки проверены: {stock_checked_at}, данные 1С от: {stock_data_as_of}", plus a warning box if `data_stale_at_check`
  - Table: №, SKU, name, color, unit, quantity, packages (e.g. "5 × 100" or "100+100+50.5")
  - Footer: total packages N, status, "Упаковал: ____ / Проверил: ____" lines, created by, printed at
- **Pages 2…N+1 — one package per page:**
  - Large label `WH-2026-000123-3/5`, request number
  - SKU, name, color, **quantity + unit in large type**
  - QR (40 mm) + URL text
- **Status rules:**
  - Printing is allowed for `CREATED` (to pack from) and `PACKED` (reprint).
  - For `CANCELLED`, every page gets a diagonal «АННУЛИРОВАН» watermark and the summary shows the reason. It stays printable for records.
- **Opening:** "Печать" on the document detail opens the print route in a new tab, which calls `window.print()` after data loads.

---

## 8. Frontend

### 8.1 `apps/admin`

**New files**
- `src/lib/warehouse.ts` — API calls (via `@oinau/api-client`), label maps for `WarehouseDocumentStatus` and `OneCState`, error-code → message mapping (alongside `src/lib/errors.ts`)
- `src/app/(panel)/packing/page.tsx` → `components/warehouse/PackingScreen.tsx`. Two tabs, with the active tab kept in the URL (`?tab=queue|documents`):
  - **Queue** (A1): table of request number, approved date, line count, a "needs linking" badge, and an "Упаковать" button
  - **Documents** (A4): filters for status and 1С state, number search
- `src/app/(panel)/packing/requests/[requestId]/page.tsx` → `components/warehouse/PackingEditor.tsx` (A2 + A3). See below.
- `src/app/(panel)/packing/documents/[id]/page.tsx` → `components/warehouse/DocumentDetail.tsx` (A5):
  - status badges (`components/ui/Badge.tsx`) for the warehouse status and the 1С state, with timestamps
  - lines and packages tables
  - buttons: «Печать», «Упаковано» (`CREATED`, with `pack`), «Аннулировать» (with `cancel`) → `components/warehouse/CancelDialog.tsx` (`components/ui/Dialog.tsx`, required reason)
- `src/app/print/warehouse-documents/[id]/page.tsx` → `components/warehouse/PrintSheet.tsx`, `SummaryPage.tsx`, `PackagePage.tsx`, `QrCode.tsx`
- `src/components/warehouse/Warehouse.module.css`, `Print.module.css`

**Split editor (`PackingEditor.tsx`)**

Top of the screen:
- request number
- "Остатки на {checked_at}"
- a stale-data warning banner (`data_stale`)
- blockers (not approved, unlinked items)

For each line:
- SKU, name, color, needed, available, shortage (shown in red)
- A list of package amount inputs with «+ коробка» / remove buttons
- A **"По N в коробке"** helper: enter a box size and it fills `⌊needed / N⌋ × N` plus the remainder. The user can still edit every amount (D10, D12).
- A running sum vs needed indicator ("500 / 500 ✓", "450 / 500 — не хватает 50"). Calculated with `src/lib/decimal.ts` (already used, so no floating-point maths — project rule 5).

At the bottom:
- the total number of packages
- **«Создать документы»**: disabled until every line matches; sends A3 with an `idempotency_key` generated when the screen loads
- If the server returns `insufficient_stock`, the shortage is shown per line from `details`.
- On success → document detail with a «Печать» prompt.

**Changed files**
- `src/lib/navigation.ts` — a new item in the «Продажи» group (or a new «Склад» group next to the existing `/stock` item): `{ href: '/packing', label: 'Упаковка', icon: 'package', requires: [Permission.WAREHOUSE_READ] }`; add `'package'` to `NavIcon` and `components/ui/Icon.tsx`
- `src/lib/auth/permissions.ts` — see §6.3
- `src/components/requests/RequestItems.tsx` — "Нужно / Доступно / Нехватка" columns per line from A8, plus "Проверено {checked_at}"
- New `src/components/requests/RequestWarehousePanel.tsx` on `RequestDetailScreen.tsx` — 1С data time, stale warning, current document (number, warehouse status, 1С state, link to `/packing/documents/[id]`) and history of cancelled documents
- `src/components/requests/RequestStatusPanel.tsx` — show `request_locked_by_warehouse` (409) as a clear message

**Dashboard (optional, not in version 1):** a «К упаковке: N» card for users with `warehouse.read`.

### 8.2 `apps/web` — public QR page

- `src/app/check/[token]/page.tsx` — server component:
  - `export const dynamic = 'force-dynamic'` (no ISR: the status can change)
  - `generateMetadata` returns `robots: { index: false, follow: false }`
  - fetches P1 through the existing server-side client in `src/lib/api`
  - 404 → `notFound()` (uses the site's `not-found.tsx`)
- `src/components/package-check/PackageCheck.tsx` + `.module.css`. Mobile-first (drivers scan with phones):
  - a big status block: green «Действительна» / red «Аннулирована»
  - the label `WH-…-3/5`, request number
  - contents (SKU, name, color, quantity + unit)
  - no header search or cart actions needed, but the normal site layout stays for brand trust
- `src/app/robots.ts` — add `Disallow: /check/`
- No link to `/check` anywhere in the navigation or the sitemap.

---

## 9. Testing strategy

Backend tests live in `apps/backend/tests/` (pytest, real PostgreSQL as today). New helpers go in `tests/warehouse_helpers.py`, next to `request_helpers.py` and `integration_helpers.py`.

### 9.1 Backend

| Rule | Test file | Cases |
|---|---|---|
| Schema constraints (§1) | `test_models.py` (extend) + `test_warehouse_models.py` | status check; `package_count > 0`; quantity > 0 on lines and packages; `(document_id, seq)` unique; the timestamp checks (export only after pack, write-off only after export, cancel-ack only if cancelled + exported); **partial unique index: a second CREATED/PACKED document for the same request fails, but one after CANCELLED works** |
| Migration | CI `alembic upgrade head` + `alembic check`; `test_warehouse_models.py` for the downgrade guard; a manual `downgrade -1` + `upgrade head` round trip before the commit | Models and migration match. Downgrade refuses while any `users` row has the role WAREHOUSE (active, inactive or soft-deleted). CI does not run `downgrade`, so the guard is a function in the migration file and is tested by calling it, not by downgrading the shared test database |
| Availability formula (§4) | `test_warehouse_availability.py` | `quantity − reserved`; CREATED and PACKED subtract; CANCELLED doesn't; confirmed + `reported_at` older → still subtracted; confirmed + `reported_at` newer → not subtracted; no stocks row → 0 and stale; several documents for the same product add up; decimal quantities (12.5 m) |
| `reported_at` (T7) | `test_integration_sync.py` (extend) | A push with an **unchanged** quantity updates `reported_at`, keeps `synced_at`, writes no audit record; a changed quantity updates all three |
| Create split — happy path | `test_admin_warehouse_packing.py` | 500 = 5×100 → 1 document + 5 packages, number `WH-YYYY-NNNNNN`, labels `…-1/5…-5/5`; mixed amounts 100+100+100+100+50+50; decimals |
| Create split — validation | same | not APPROVED → 409; GENERAL request → 404; sum ≠ quantity → 422 with details; missing / extra / duplicate line → 422; unlinked item → 422; more than the max packages → 422; no / two active warehouses → 409 |
| Shortage blocks (D16) | same | Available 450, needed 500 → 409 `insufficient_stock` with per-line details; nothing inserted |
| Stale data doesn't block (D27) | same | Stock data 25 h old → 201, `data_stale_at_check = true` |
| Idempotency | same | Same key + same body → 200 with the same document; same key + different body → 409; numbers aren't consumed twice |
| Numbering (D32) | same | Cancel, then re-split → a new, higher number; the old number is never reused |
| **Success criterion: two requests, the same stock** | `test_warehouse_concurrency.py` | Stock 500; request A needs 500, request B needs 300. **Run A3 for both at the same time** (`asyncio.gather` with two separate sessions/connections). Exactly one gets 201 and the other gets 409 `insufficient_stock`. Repeat 20× to catch flakiness. Also: two creates for the **same** request at the same time → one 201, one 409 `active_document_exists`. |
| Sequential double use | `test_warehouse_availability.py` | A packed (not yet confirmed by 1С) → B blocked; A cancelled → B allowed; A confirmed + newer push with lower quantity → B sees the correct number |
| State machine (§2.1) | `test_warehouse_state.py` | create → pack → cancel; create → cancel; pack twice = no change; pack after cancel → 409; cancel needs a reason; audit actions written |
| Request lock (§2.3) | `test_admin_requests.py` (extend) | Active CREATED document: change to CANCELLED / IN_PROGRESS / COMPLETED → 409; PACKED: COMPLETED allowed, others 409; after cancelling the document, any status works |
| Permissions (§6) | `test_warehouse_permissions.py` | A WAREHOUSE user: 200 on A1–A7, **403** on `/admin/requests`, `/admin/requests/{id}`, `/admin/stock`, product writes, `/admin/users`; VIEWER and CONTENT_MANAGER get 403 on A1–A7; MANAGER gets 200 on everything |
| No leaks | `test_warehouse_permissions.py` | Walk every A1–A7 response (and P1) recursively and assert none of these keys appear: `unit_price_snapshot`, `line_total_snapshot`, `total_estimate`, `price`, `customer_name`, `phone`, `email`, `company`, `bin`, `city`, `comment` — the same approach as `test_admin_integration_status.py` |
| Integration list / ack (§3.3) | `test_integration_warehouse.py` | CREATED isn't listed; PACKED is listed as `write_off`; after ack it isn't listed; a repeated ack keeps `external_id`; cancel after ack → listed as `cancel`; cancel-ack removes it; cancel **between list and ack** → ack returns `status=CANCELLED` and the document is then in the cancel list; write-off before ack → 409; write-off on a cancelled + acked document → 200 |
| Integration security | `test_integration_security.py` (extend) | Missing `warehouse:read` / `warehouse:write` → 403 `integration_scope_denied`; integration disabled → 503; unknown key → 401; `sync_log` row written |
| Public check page (§3.2) | `test_public_package_check.py` | Valid → `VALID`; after cancel → `CANCELLED`; unknown UUID and malformed token → identical 404; `Cache-Control: no-store`; rate limit → 429; no forbidden keys |
| Permissions table | `test_security.py` / users tests (extend) | `ROLE_PERMISSIONS[WAREHOUSE]` is exactly the three permissions; a WAREHOUSE user can be created by an admin |
| OpenAPI types | CI (existing) | `packages/api-types/src/schema.d.ts` regenerated with `make gen-types`; CI fails if it's out of date |

### 9.2 Frontend (Vitest + Testing Library)

| App | Test | Cases |
|---|---|---|
| admin | `tests/warehouse-editor.test.tsx` | The sum indicator uses decimal maths (`0.1 + 0.2` style cases); the "По N" helper (500 / 100 → 5×100; 530 / 100 → 5×100 + 30); save disabled until all lines match; `insufficient_stock` details shown per line; the idempotency key is stable across retries |
| admin | `tests/warehouse-print.test.tsx` | Renders 1 summary + N package pages; each package page has an `<svg>` QR and the `check_url` text; **no price strings**; cancelled → watermark |
| admin | `tests/warehouse-detail.test.tsx` | Buttons follow permissions (no `warehouse.cancel` → no cancel button); OneCState labels |
| admin | `tests/shell.test.tsx` + `tests/rbac.test.tsx` (extend) | «Упаковка» is visible only with `warehouse.read`; a WAREHOUSE user doesn't see «Заявки» or «Товары» |
| admin | `tests/requests.test.tsx` (extend) | Availability columns and the stale banner; the 409 `request_locked_by_warehouse` message |
| web | `tests/PackageCheck.test.tsx` | Valid and cancelled states; not-found; `noindex` metadata |

### 9.3 Manual checks (added to the README "Ручная проверка" list)

1. Approve a request for 500 × `AKO-GV-001` (seed stock 500).
2. Log in as a **WAREHOUSE** user → «Упаковка» → «Упаковать» → "По 100" → «Создать документы». **Time it: under 2 minutes** (success criterion).
3. Print → check A4 layout: 1 summary + 5 packages, no prices, QR codes scan on a phone and open `/check/...` showing «Действительна».
4. «Упаковано». Simulate 1С with `app/scripts/fake_1c_warehouse.py` (a new dev-only script that uses a test API key with sample data shaped like 1С's): list → ack → write-off → push stock 0.
5. Second request for 300 → blocked with a shortage at every step until the stock push.
6. Cancel the document → QR page shows «Аннулирована»; 1С list shows a cancel event.

---

## 10. Implementation order (suggested, for GitHub issues)

1. Migration + models + enums + permissions/role (no endpoints)
2. Availability calculation + `reported_at` in stock sync + tests
3. Admin A2/A3 (create split) with locking + concurrency test
4. A1, A4–A7 + state machine + request status guard
5. A8 + admin request page columns and panel
6. Admin packing screens (queue, editor, detail)
7. Print page + QR
8. Public P1 + web `/check/[token]`
9. Integration I1–I4 + scopes + fake 1С script
10. Docs: `docs/integrations.md`, `docs/database.md`, README smoke steps, an ADR in `docs/adr/`

Each step is deployable on its own. Steps 1–5 already give managers pain-point A (the stock check).

---

## 11. Open risks and assumptions

### Open questions (from `_docs/decisions.md`)
| # | Question | Risk if unanswered | Current design behaviour |
|---|---|---|---|
| Q1 | Does 1С `reserved` already include this request? | Double subtraction → false shortages | Subtracts both (safe, may block wrongly). Fallback idea: ignore `reserved` for requests that 1С has acknowledged. |
| Q2 | Does every 1С push include every product? | If not, confirmed documents stay subtracted for products 1С didn't resend | Safe but too low. Ask 1С for full snapshots. A "waiting for 1С stock update" hint can be added to A8 if this happens in practice. |
| Q3 | Does 1С confirm write-off reversals? | Can't show "reversal done" | Not tracked; `CANCEL_READ` is the last 1С state. |
| Q4 | Who may cancel? Reason required? | Wrong permission mapping | WAREHOUSE + MANAGER, reason required |
| Q5 | Document / QR page language | Reprint templates | Russian |

### Risks
| Risk | Mitigation |
|---|---|
| **No real 1С yet** — the contract is our proposal (`docs/integrations.md` §3.1) | Keep `ONE_C_INTEGRATION_ENABLED=false` in production; test with `fake_1c_warehouse.py`; check the contract against the real export before switching on |
| The global packing lock becomes a bottleneck | Unlikely at current volume. Switch to sorted product-row locks (`products … FOR UPDATE`) without changing the API. |
| Browser print differences (margins, scaling) | Fixed `@page` margins; test in Chrome and Edge on the warehouse PC; label printer later (out of scope) |
| A QR code printed for a cancelled document is still stuck on a box | The QR page shows «Аннулирована» live (no cache); the reprint of a new split has new tokens |
| Request lines without `product_id` (unrecognized SKU list) can't be packed | Blocked with a clear error; the manager must link the product first (needs an admin "link product to line" action — **not designed here**, to confirm) |
| Stale stock data (> 24 h) doesn't block | Warning on screen and on the printed summary (D27); the business accepted this |
| Year in the number uses `Asia/Almaty`; requests use the server moment's year | Agree on one rule; difference only around midnight on 31 December |
| Users soft-deleted while referenced by documents | FKs are `SET NULL`; names are shown from the users table (users aren't hard-deleted), so history stays readable |

### Assumptions
- Only `kind = CART` requests can be packed; `GENERAL` requests have no lines.
- "Packed" confirms the whole document at once.
- Package amounts > 0, at most 3 decimal places (`NUMERIC(14,3)`).
- One active warehouse; anything else is a configuration error.
- The existing `/stock` admin screen doesn't change. It still shows raw `quantity`/`reserved` from 1С, not "available".
- WAREHOUSE users are created by ADMIN/SUPERADMIN in the existing users screen.
- Audit actions: `warehouse.document_created`, `warehouse.document_packed`, `warehouse.document_cancelled`, plus `warehouse.document_exported`, `warehouse.write_off_confirmed`, `warehouse.cancel_exported` with `actor="1c"`.
