#!/usr/bin/env bash
# Резервная копия production-базы OINAU PRO.
#
# Запускается НА СЕРВЕРЕ, из каталога репозитория:
#     ./infra/backup/pg-backup.sh
#
# По расписанию — через systemd-таймер (infra/backup/systemd/), установка
# описана в docs/deployment.md. Сам скрипт расписания не создаёт: cron
# внутри контейнера базы означал бы, что копии живут там же, где данные.
#
# Что делает:
#   1. pg_dump в custom-формате (-Fc) — он уже сжат и годится для
#      частичного восстановления отдельных таблиц;
#   2. кладёт файл в $BACKUP_DIR вне тома PostgreSQL;
#   3. проверяет, что дамп читается (pg_restore --list);
#   4. по желанию отправляет копию за пределы сервера через rclone;
#   5. удаляет копии старше $BACKUP_RETENTION_DAYS.
#
# Копия на том же диске защищает от ошибочного DELETE, но не от потери
# сервера. Внешнее хранилище ($BACKUP_REMOTE) закрывает второй случай.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env.production}"
COMPOSE_FILE="${COMPOSE_FILE:-$REPO_ROOT/infra/docker/compose.prod.yaml}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Не найден $ENV_FILE" >&2
  exit 1
fi

# set -a экспортирует всё, что присвоено в файле. Файл читается, а не
# исполняется как скрипт: значения там простые KEY=VALUE.
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

BACKUP_DIR="${BACKUP_DIR:-/var/backups/oinau}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
BACKUP_REMOTE="${BACKUP_REMOTE:-}"
POSTGRES_USER="${POSTGRES_USER:?POSTGRES_USER не задан}"
POSTGRES_DB="${POSTGRES_DB:?POSTGRES_DB не задан}"

COMPOSE=(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE")

mkdir -p "$BACKUP_DIR"
# Дампы содержат телефоны и адреса клиентов из заявок — каталог закрыт.
chmod 700 "$BACKUP_DIR"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TARGET="$BACKUP_DIR/oinau-$STAMP.dump"
TMP="$TARGET.part"

echo "[$(date -Is)] Снимаю дамп $POSTGRES_DB -> $TARGET"

# Пароль передаётся контейнеру переменной окружения, а не в командной
# строке: аргументы видны в выводе ps любому пользователю сервера.
# -T отключает псевдотерминал, иначе в дамп попадут управляющие символы.
"${COMPOSE[@]}" exec -T \
  -e PGPASSWORD="$POSTGRES_PASSWORD" \
  postgres pg_dump \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --format=custom \
  --compress=9 \
  --no-owner \
  --no-privileges \
  >"$TMP"

# Файл переименовывается только после успешного дампа: наполовину
# записанный файл не должен выглядеть как готовая копия.
mv "$TMP" "$TARGET"
chmod 600 "$TARGET"

# Дамп, который не читается, — это не резервная копия. Проверка дешёвая:
# читается только оглавление архива, данные не разворачиваются.
# Файл кладётся во временный путь внутри контейнера: pg_restore --list
# требует файл, по которому можно перемещаться, а канал этого не даёт.
if ! "${COMPOSE[@]}" exec -T postgres sh -c \
  'cat > /tmp/verify.dump && pg_restore --list /tmp/verify.dump > /dev/null; rc=$?; rm -f /tmp/verify.dump; exit $rc' \
  <"$TARGET"; then
  echo "ОШИБКА: дамп $TARGET не читается pg_restore" >&2
  exit 1
fi

SIZE="$(du -h "$TARGET" | cut -f1)"
echo "[$(date -Is)] Готово: $TARGET ($SIZE)"

if [[ -n "$BACKUP_REMOTE" ]]; then
  echo "[$(date -Is)] Копирую во внешнее хранилище: $BACKUP_REMOTE"
  rclone copy "$TARGET" "$BACKUP_REMOTE" --no-traverse
fi

# Удаляются только файлы этого скрипта: шаблон имени фиксированный.
DELETED="$(find "$BACKUP_DIR" -maxdepth 1 -name 'oinau-*.dump' -mtime "+$BACKUP_RETENTION_DAYS" -print -delete | wc -l)"
echo "[$(date -Is)] Удалено копий старше $BACKUP_RETENTION_DAYS дней: $DELETED"
