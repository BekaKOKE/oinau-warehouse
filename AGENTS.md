# AGENTS.md

Context for AI coding agents working in this repository (oinau-pro.kz, playground parts catalog and request system).

## Current work: warehouse feature

We are adding a warehouse packing feature (packing documents with QR codes, 1С exchange). Read these before any task, in this order:

1. `_docs/plan.md` — brainstorm result and decisions D1–D34
2. `_docs/decisions.md` — technical decisions T1–T10
3. `_docs/warehouse-design.md` — the detailed design (data model, API, locking, UI)
4. `_docs/process.md` — how we work (issues, roles, loop)

If code and design disagree, stop and write it in the issue; do not silently pick one.

## Stack

- Backend: `apps/backend` — FastAPI, SQLAlchemy async, Alembic, PostgreSQL 16, Redis, ARQ. Tools: `uv`, `pytest`, `ruff`, `mypy`.
- Frontend: `apps/web` and `apps/admin` — Next.js 15, pnpm workspaces.
- API types: `packages/api-types/src/schema.d.ts` is generated from OpenAPI and committed. After any API change run `make gen-types`.
- Last Alembic revision before the warehouse work: `e7a2b9c4d150`.

## Commands

Backend (run from `apps/backend`):

- Module tests: `uv run pytest tests/<file_or_module>` — use this, not the full suite
- Lint: `uv run ruff check .` and `uv run ruff format --check .`
- Types: `uv run mypy app`
- Migrations check: `uv run alembic upgrade head` on a clean database

Frontend (run from the repository root):

- `pnpm --filter @oinau/admin test`, `pnpm --filter @oinau/admin lint`, `pnpm --filter @oinau/admin typecheck` (same for `@oinau/web`)

Infrastructure: `make up-infra` starts PostgreSQL and Redis. Local ports are set in `.env` (Postgres 5433, Redis 6380); `.env` is never committed.

## Safety rules (hard, never break)

1. Work only on branch `feature/warehouse`. Never commit or push to `main`. Never force-push. Never rewrite history that is already pushed.
2. Migrations are additive only: new tables and new columns. Never drop or rename existing tables/columns, never edit an old migration.
3. The site never changes stock quantities. 1С owns stock (decision D1). Warehouse code only reads stock and writes its own tables.
4. The 1С integration is off by default (`ONE_C_INTEGRATION_ENABLED`). Nothing may require a real 1С connection.
5. No secrets in code, tests, docs or commit messages. Do not read, print or commit `.env`. Gitleaks runs in CI.
6. The `WAREHOUSE` role must never see prices or client contacts. The public QR check page shows no prices and no client name.
7. Do not change existing behaviour of catalog, requests, users or integration endpoints except where the issue says so. Existing tests must stay green.
8. Run only the tests of the module you changed. The full suite is slow (about 1.5 h) and runs in CI.

## Git and attribution

- Commit author is the repository owner's configured git identity. Do not change git config.
- Do NOT add `Co-Authored-By` lines, "Generated with ..." lines, or any mention of AI/Claude in commits, issues, issue comments or pull requests. Write them as plain human project notes.
- One commit per finished issue, message: `<short summary> (#<issue number>)`.
- Final result goes into a pull request from `feature/warehouse` to `main`; the repository owner merges and deploys it.

## Code style

- Follow the patterns already in the repository (module layout in `app/modules/<name>/`, services, routers, schemas). Look at an existing module before writing a new one.
- Quantities are decimals, never floats.
- Every state change writes an audit record.
- Keep changes small and inside the scope of the current issue.
