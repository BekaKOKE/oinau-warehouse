# Backlog — Warehouse Packing Feature

Based on `_docs/warehouse-design.md` §10. Section numbers (§) refer to that file; decisions T1–T10 are in `_docs/decisions.md`.

## 1. Make backend tests run locally and add the first warehouse test
Goal: A green local `pytest` run that includes one test for the new `app/modules/warehouse/` module.
Description: Start PostgreSQL 16 with the required extensions (`make up-infra`, or a local install plus `infra/docker/postgres/init.sql`), install the backend dev dependencies into `apps/backend/.venv`, and run the existing suite; `tests/conftest.py` applies the Alembic migrations itself. Then create the empty `app/modules/warehouse/` package with a pure function `build_document_number(value, moment)` that returns `WH-2026-000123` (design §1.6), and test it in `tests/test_warehouse_numbering.py`, which needs no database. Add any setup steps that were missing to the README's "Запуск без Docker" section.

## 2. Add the warehouse tables, models and migration
Goal: The database can store packing documents, lines and packages, and the `WAREHOUSE` role exists in the backend, the API types and the admin app.
Description: Create the models `WarehouseDocument`, `WarehouseDocumentLine` and `WarehousePackage` and their enums in `app/modules/warehouse/`, exactly as in design §1.1–§1.3 and §1.7, register them in `app/db/base.py`, and write one additive Alembic revision after `e7a2b9c4d150` that recreates `ck_users_role`, adds `stocks.reported_at`, creates `warehouse_document_number_seq`, and creates the three tables with all their checks and partial unique indexes (§1.8); its downgrade refuses to run while any user has the `WAREHOUSE` role. Add `UserRole.WAREHOUSE` with no permissions yet, regenerate the API types (`make gen-types`), and add the role's label ("Кладовщик") and hint in the admin app so that it still typechecks. Cover the constraints in `tests/test_warehouse_models.py`, especially "one active document per request", update `docs/database.md`, and record the decision in a new ADR `docs/adr/0007-dokumenty-upakovki-sklada.md`.

## 3. Add the warehouse permissions to the role matrix
Goal: The `WAREHOUSE` role and the managers get the `warehouse.read`, `warehouse.pack` and `warehouse.cancel` permissions.
Description: Add the three permission constants and the role mapping from the design §6.1 table to `app/modules/users/permissions.py`, and mirror the codes and their labels in `apps/admin/src/lib/auth/permissions.ts`. The `WAREHOUSE` role itself, its label and its hint already exist from task 2, where the role has an empty permission set. Extend the RBAC tests on both sides (backend `test_security.py` / `test_admin_users.py`, admin `tests/rbac.test.tsx`) to prove that `WAREHOUSE` has no `request.read` or `catalog.read`, and that an admin can create a `WAREHOUSE` user.

## 4. Calculate available stock and record 1С push times
Goal: The backend can say how much of a product is really available, taking site documents into account.
Description: Implement the formula from design §4 (`quantity − reserved − pending site documents`), together with the "stale data" flag, in `app/modules/warehouse/availability.py` as one SQL query per request. Change `StockSyncService._apply_stock` in `app/modules/integration/service_sync.py` so that every 1С push sets `stocks.reported_at`, even when the quantity didn't change, while `synced_at` and the audit log behave as before (T7). Test every formula and `reported_at` case listed in design §9.1.

## 5. Create a packing split with safe locking
Goal: A warehouse user can split an approved request into packages, and two people can never pack the same stock twice.
Description: Build A2 `GET /admin/warehouse/requests/{id}/packing` and A3 `POST /admin/warehouse/requests/{id}/documents` in `app/modules/warehouse/router_admin.py`, with all the validations and error codes from design §3.1. Use the locking sequence from §5.1: idempotency check, global advisory lock, request row lock, availability check, insert. Add `tests/test_admin_warehouse_packing.py` and `tests/test_warehouse_concurrency.py`, where the success criterion is that stock 500 with two requests for 500 and 300 at the same time lets exactly one succeed.

## 6a. Manage documents and expose availability in the backend
Goal: The backend can list, show, pack and cancel warehouse documents, and managers can read availability per request.
Description: Add A1 (queue), A4 (list), A5 (detail), A6 (pack) and A7 (cancel) with the state machine from design §2.1 and audit actions, plus A8 `GET /admin/requests/{id}/warehouse` and the guard in `AdminRequestService.update_status` that blocks status changes while a document is active (§2.3). Run `make gen-types` so `packages/api-types/src/schema.d.ts` is updated. Tests cover the transitions, the request lock, the permission matrix, and that no price or contact field appears in any warehouse response (§9.1).

## 6b. Show availability to managers in the admin app
Goal: Managers see "Нужно / Доступно / Нехватка" and the warehouse status on the request page.
Description: In the admin app, add the "Нужно / Доступно / Нехватка" columns to `components/requests/RequestItems.tsx` and a new `RequestWarehousePanel.tsx` on the request page, using the endpoint A8 and the generated API types. Add Vitest tests for the columns and the panel (§9.2).

## 7. Build the admin packing screens
Goal: Warehouse users can do the whole packing flow in the admin panel without touching the API directly.
Description: Add the «Упаковка» navigation item and three screens under `apps/admin/src/app/(panel)/packing/` as in design §8.1: a queue / documents list with tabs, the split editor, and the document detail page with Pack and Cancel actions (cancel needs a reason). The split editor checks each line's sum with `lib/decimal.ts`, has a "По N в коробке" helper, generates an idempotency key when it opens, and calls the existing endpoints A1–A7 through `src/lib/warehouse.ts`. Add Vitest tests for the editor, the detail page and navigation visibility (§9.2).

## 8. Print documents with QR codes and add the public check page
Goal: The warehouse can print A4 documents with QR codes, and anyone who scans a QR code sees whether the box is valid.
Description: Add the public endpoint P1 `GET /api/v1/public/warehouse-packages/{token}` (rate limit, `no-store`, the same 404 for unknown and malformed tokens) and the web page `apps/web/src/app/check/[token]/`, which is mobile-first, `noindex`, and blocked in `robots.ts` (§3.2, §8.2). In the admin app, add the print route `apps/admin/src/app/print/warehouse-documents/[id]/`: one summary page plus one page per package, a QR drawn as SVG by a pinned npm library, and a "cancelled" watermark (§7). Add the manual print-and-scan steps to the README smoke checklist (§9.3).

## 9. Link an unrecognized product to a request line
Goal: A manager can attach a catalog product to a request line that came in without one, so that the line can be packed.
Description: Request lines from a pasted SKU list can have `request_items.product_id = NULL`, and packing blocks them with `request_item_unlinked` (design §3.1, §11). Add a small admin endpoint (permission `request.write`) that sets `product_id` on one line only while the request has no active warehouse document, keeps the client's snapshots unchanged, and writes an audit record. Add a "Привязать товар" action with product search in `components/requests/RequestItems.tsx`, plus tests for the endpoint and the action.

## 10. Connect the 1С exchange for warehouse documents
Goal: 1С can collect packed documents, confirm reading and write-off, and receive cancellations through the integration API.
Description: Add the scopes `warehouse:read` and `warehouse:write` to `IntegrationScope`, the endpoints I1–I4 in `app/api/v1/integration.py`, and the logic in `app/modules/integration/service_warehouse.py`, following the existing requests pattern (list → ack → write-off → cancel-ack) with `sync_log` and audit records (design §3.3). Write a dev-only `app/scripts/fake_1c_warehouse.py` that plays 1С with sample data, and add `tests/test_integration_warehouse.py`, including the "cancelled between list and ack" case. Update `docs/integrations.md` with the new contract and the open questions Q1–Q3 for the 1С developer.
