# syntax=docker/dockerfile:1.7
# Один Dockerfile на приложение, разные stage под dev и prod.
# Два отдельных файла со временем расходятся — этого избегаем.

FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_SYSTEM_PYTHON=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
WORKDIR /app

# ---------------------------------------------------------------- dependencies
# Зависимости ставятся ДО копирования кода, иначе каждая правка кода
# инвалидирует слой и пересобирает всё.
FROM base AS deps
COPY pyproject.toml ./
RUN mkdir -p app && touch app/__init__.py

# ------------------------------------------------------------------ development
FROM deps AS development
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -e ".[dev]"
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ------------------------------------------------------------------- production
FROM deps AS production
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system .
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
# Приложение не работает от root
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1
# Миграции здесь НЕ запускаются: при нескольких репликах это гонка.
# alembic upgrade head — отдельный шаг деплоя.
# Число рабочих процессов задаётся окружением: на VPS с 2 ядрами четыре
# процесса только отнимают память. exec сохраняет PID 1 за uvicorn,
# иначе docker stop ждёт таймаут вместо мягкой остановки.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-4} --no-server-header --no-access-log"]
