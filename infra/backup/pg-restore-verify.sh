#!/usr/bin/env bash
# Проверка восстановимости резервной копии OINAU PRO.
#
#     ./infra/backup/pg-restore-verify.sh /var/backups/oinau/oinau-20260919T030000Z.dump
#
# Копия, которую ни разу не разворачивали, — это предположение, а не
# резервная копия. Скрипт разворачивает дамп во ВРЕМЕННУЮ базу внутри
# того же контейнера PostgreSQL, сверяет ключевые таблицы и удаляет её.
#
# Рабочая база НЕ ЗАТРАГИВАЕТСЯ: имя временной базы генерируется, а
# восстановление идёт с --dbname на неё. Скрипт не умеет восстанавливать
# поверх рабочей базы — это делается вручную и осознанно (docs/deployment.md).

set -euo pipefail

DUMP="${1:?Укажите путь к файлу дампа}"
[[ -f "$DUMP" ]] || {
  echo "Не найден файл $DUMP" >&2
  exit 1
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env.production}"
COMPOSE_FILE="${COMPOSE_FILE:-$REPO_ROOT/infra/docker/compose.prod.yaml}"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

POSTGRES_USER="${POSTGRES_USER:?}"
VERIFY_DB="verify_$(date -u +%Y%m%d%H%M%S)"
COMPOSE=(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE")

psql_run() {
  "${COMPOSE[@]}" exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" postgres \
    psql --username "$POSTGRES_USER" --dbname "$1" --no-psqlrc -qtAX -c "$2"
}

cleanup() {
  echo "[$(date -Is)] Удаляю временную базу $VERIFY_DB"
  psql_run postgres "DROP DATABASE IF EXISTS \"$VERIFY_DB\"" >/dev/null || true
}
trap cleanup EXIT

echo "[$(date -Is)] Создаю временную базу $VERIFY_DB"
psql_run postgres "CREATE DATABASE \"$VERIFY_DB\"" >/dev/null

echo "[$(date -Is)] Восстанавливаю $DUMP"
# --no-owner/--no-privileges: владельцы и гранты в временной базе не важны.
# Код возврата pg_restore игнорировать нельзя, но предупреждения о
# расширениях он выдаёт и при штатном восстановлении — поэтому решение
# принимается по сверке данных ниже, а вывод сохраняется целиком.
"${COMPOSE[@]}" exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" postgres \
  pg_restore --username "$POSTGRES_USER" --dbname "$VERIFY_DB" \
  --no-owner --no-privileges --exit-on-error <"$DUMP"

echo "[$(date -Is)] Сверяю содержимое"
FAILED=0
for table in products categories requests users customers content_sections; do
  count="$(psql_run "$VERIFY_DB" "SELECT count(*) FROM $table" || echo ERR)"
  printf '  %-20s %s\n' "$table" "$count"
  [[ "$count" == "ERR" ]] && FAILED=1
done

version="$(psql_run "$VERIFY_DB" "SELECT version_num FROM alembic_version" || echo ERR)"
echo "  alembic_version      $version"
[[ "$version" == "ERR" || -z "$version" ]] && FAILED=1

if [[ "$FAILED" -ne 0 ]]; then
  echo "ПРОВЕРКА НЕ ПРОЙДЕНА: копия развернулась не полностью" >&2
  exit 1
fi

echo "[$(date -Is)] Копия восстановима"
