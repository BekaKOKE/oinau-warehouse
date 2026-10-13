# Развёртывание в production

Документ описывает установку OINAU PRO на VPS Hoster.kz под доменом
`oinau-pro.kz` с Cloudflare перед сервером и Cloudflare R2 для медиа.

Порядок разделов — это и есть порядок действий. Пропускать шаги нельзя:
каждый следующий опирается на предыдущий.

```
Интернет
   │
Cloudflare (DNS + прокси + TLS для посетителя)
   │  HTTPS
VPS Hoster.kz
   │
Caddy (80/443, единственный открытый порт)
   ├── /            → web    (Next.js, витрина)
   ├── /admin*      → admin  (Next.js, basePath=/admin)
   ├── /api/*       → backend (FastAPI)
   └── /health      → backend (liveness)
        │
   worker (ARQ) ── Redis ── PostgreSQL     (сеть без выхода в интернет)
        │
   Cloudflare R2 (изображения)
```

Ключевое архитектурное решение: **всё живёт на одном домене**. Админка —
по пути `/admin`, API — по пути `/api`. Отдельные поддомены `admin.` и
`api.` не заводятся, и это не экономия: cookie refresh-токена привязана
к пути `/api/v1/admin/auth` того же origin и работает с `SameSite=strict`
без послаблений, а браузер не делает preflight на каждый запрос.

---

## 0. Что нужно иметь на руках

Без этих доступов деплой начинать нечего:

| Что                          | Где берётся       | Для чего              |
| ---------------------------- | ----------------- | --------------------- |
| VPS Hoster.kz, root или sudo | панель Hoster.kz  | сам сервер            |
| Домен `oinau-pro.kz`         | регистратор       | адрес сайта           |
| Аккаунт Cloudflare           | cloudflare.com    | DNS, TLS, R2          |
| Cloudflare R2: бакет + ключ  | панель Cloudflare | изображения товаров   |
| Почтовый сервис (SMTP)       | хостинг почты     | письма клиентам       |
| Telegram-бот (необязательно) | @BotFather        | уведомления о заявках |

---

## 1. Подготовка VPS

Рекомендуемый минимум: 2 vCPU, 4 ГБ RAM, 40 ГБ диска, Ubuntu 22.04/24.04.
4 ГБ — не запас: PostgreSQL, Redis, два процесса Next.js и четыре воркера
uvicorn на 2 ГБ упрутся в OOM при первом же импорте каталога.

### 1.1. Пользователь деплоя

Работать под root не нужно ни на одном шаге после установки пакетов.

```bash
adduser --disabled-password --gecos "" deploy
usermod -aG sudo deploy
mkdir -p /home/deploy/.ssh
cp ~/.ssh/authorized_keys /home/deploy/.ssh/
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh && chmod 600 /home/deploy/.ssh/authorized_keys
```

### 1.2. SSH

В `/etc/ssh/sshd_config`:

```
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
```

```bash
sshd -t && systemctl restart ssh
```

Проверьте вход `ssh deploy@<ip>` **в отдельном окне, не закрывая текущее**:
ошибка в конфигурации SSH при закрытой сессии означает поездку в
панель восстановления.

### 1.3. Межсетевой экран

Открыты только SSH и HTTP(S). Порты PostgreSQL, Redis и backend наружу
не смотрят вообще — ни через firewall, ни через Docker.

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp        # HTTP/3
ufw enable
ufw status verbose
```

> **Docker и ufw.** Docker публикует порты в обход ufw, дописывая правила
> в цепочку `DOCKER`. В нашем `compose.prod.yaml` наружу публикует порты
> только прокси (80/443), поэтому конфликта нет. Но если однажды кто-то
> добавит `ports:` к postgres «на пять минут для отладки» — порт станет
> доступен из интернета, и ufw этому не помешает. Не добавляйте.

### 1.4. Docker

```bash
curl -fsSL https://get.docker.com | sh
usermod -aG docker deploy
systemctl enable --now docker
```

Выйдите и войдите заново, чтобы членство в группе `docker` применилось.

### 1.5. Автоматические обновления безопасности

```bash
apt install -y unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades
```

---

## 2. Cloudflare: DNS

В панели Cloudflare добавьте домен `oinau-pro.kz` и переключите NS
у регистратора на выданные Cloudflare.

| Тип   | Имя   | Значение                  | Прокси                     |
| ----- | ----- | ------------------------- | -------------------------- |
| A     | `@`   | IP VPS                    | Proxied (оранжевое облако) |
| A     | `www` | IP VPS                    | Proxied                    |
| CNAME | `cdn` | публичный адрес бакета R2 | Proxied                    |

Записи `admin` и `api` **не нужны**: и то и другое живёт на основном домене.

---

## 3. Cloudflare R2: хранилище изображений

1. **R2 → Create bucket**, имя `oinau-media`, регион автоматический.
2. **R2 → Manage API tokens → Create API token**:
   - права **Object Read & Write**;
   - область — **только бакет `oinau-media`**, не весь аккаунт;
   - сохраните `Access Key ID`, `Secret Access Key` и адрес
     `https://<account_id>.r2.cloudflarestorage.com` — секрет больше
     не покажут.
3. **Бакет → Settings → Public access → Connect a custom domain**:
   домен `cdn.oinau-pro.kz`. Cloudflare сам создаст нужную DNS-запись.
4. **Бакет → Settings → CORS policy** — без неё админка не сможет
   загрузить изображение: presigned PUT уходит из браузера прямо в R2.

```json
[
  {
    "AllowedOrigins": ["https://oinau-pro.kz"],
    "AllowedMethods": ["PUT"],
    "AllowedHeaders": ["content-type"],
    "MaxAgeSeconds": 3600
  }
]
```

### Как устроен доступ к файлам

Схему задаёт само приложение, менять её в панели не нужно:

| Префикс ключа                                   | Доступ    | Кто читает                       |
| ----------------------------------------------- | --------- | -------------------------------- |
| `products/*/original.*`, `content/*/original.*` | приватный | только backend и воркер          |
| `products/*/variants/*`, `content/*/variants/*` | публичный | браузер через `cdn.oinau-pro.kz` |

Оригиналы нужны для перегенерации вариантов и наружу не отдаются.
В браузер уходят только URL вида `https://cdn.oinau-pro.kz/products/<uuid>/variants/large.webp`.
Ключи доступа R2 в браузер не попадают никогда: пресайн делает backend,
а сама ссылка живёт `UPLOAD_PRESIGN_TTL_SECONDS` (по умолчанию 10 минут).

> **Публичный доступ ко всему бакету включать нельзя.** Если в
> `Public access` открыть бакет целиком, оригиналы станут доступны по
> прямой ссылке всем, кто угадает UUID.

---

## 4. Код и конфигурация на сервере

```bash
sudo mkdir -p /srv && sudo chown deploy:deploy /srv
cd /srv
git clone <адрес репозитория> oinau-pro
cd oinau-pro

cp .env.production.example .env.production
chmod 600 .env.production
```

Заполните `.env.production`. Обязательные значения помечены в файле
словом `ЗАПОЛНИТЬ`:

```bash
openssl rand -hex 32      # SECRET_KEY
openssl rand -base64 24   # POSTGRES_PASSWORD
```

Отдельно проверьте:

- `SITE_DOMAIN=oinau-pro.kz` и `ACME_EMAIL` — на этот адрес Let's Encrypt
  пишет об истечении сертификата;
- `TRUSTED_PROXY_HOPS=2` — Cloudflare плюс Caddy. Если прокси Cloudflare
  выключен (серое облако), значение должно быть `1`. Ошибка в большую
  сторону позволяет подделать IP клиента заголовком, в меньшую — весь
  трафик считается одним клиентом и упирается в ограничение частоты;
- `CDN_BASE_URL` и `NEXT_PUBLIC_CDN_BASE_URL` должны совпадать;
- `SMTP_*` — настоящий почтовый сервер. Значение `mailpit` backend
  отклонит при старте;
- `NOTIFY_EMAILS` — без него деловые письма о заявках не уходят вообще
  (события даже не попадают в очередь: получателей нет);
- `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID` — без них канал отдаёт
  `skipped`. Если заявки должны падать в отдельную тему форумной
  супергруппы, задайте ещё `TELEGRAM_MESSAGE_THREAD_ID`; как получить
  оба идентификатора — в [`integrations.md`](integrations.md), раздел 2.1.

Проверка конфигурации до запуска:

```bash
make prod-config
```

---

## 5. Первый запуск

```bash
make prod-build     # сборка образов, 5–15 минут на первый раз
make prod-up
make prod-ps        # все сервисы должны быть healthy
```

`NEXT_PUBLIC_*` встраиваются в браузерный бандл **на этапе сборки**.
Изменение домена, адреса API или CDN требует `make prod-build`, а не
только перезапуска.

### Миграции

```bash
make prod-migrate
```

Отдельным шагом, а не при старте backend: при нескольких процессах
одновременный `alembic upgrade` — это гонка за блокировкой таблицы
версий. Расширения PostgreSQL (`pg_trgm`, `unaccent`, `btree_gist`,
`citext`, `pgcrypto`) создаёт первая миграция, отдельных действий
не требуется.

### Первый администратор

```bash
make prod-superuser
```

Демонстрационные данные (`app.scripts.seed`) в production запускать
нельзя, и скрипт сам это запрещает.

---

## 6. TLS и режим Cloudflare

Caddy выпускает сертификат Let's Encrypt автоматически при первом
обращении к домену и продлевает его сам. Ничего настраивать не нужно.

В Cloudflare: **SSL/TLS → Overview → Full (strict)**.

- `Flexible` **использовать нельзя**: Cloudflare пойдёт на сервер по
  HTTP, Caddy ответит редиректом на HTTPS, и получится бесконечный цикл
  редиректов. Кроме того, участок «Cloudflare → сервер» останется
  незашифрованным.
- `Full` (без strict) принимает самоподписанный сертификат и не проверяет
  его — защита от подмены на этом участке теряется.

Дополнительно в Cloudflare:

- **SSL/TLS → Edge Certificates → Always Use HTTPS**: включить;
- **Minimum TLS Version**: 1.2;
- **Automatic HTTPS Rewrites**: включить;
- **HSTS**: можно не включать на стороне Cloudflare — заголовок уже
  отдают backend и Caddy. Если включаете — помните, что откатить HSTS
  у уже побывавших на сайте браузеров нельзя до истечения max-age.

Если сертификат не выпускается, самая частая причина — Cloudflare в
режиме `Flexible` либо закрытый порт 80 (ACME HTTP-01 ходит именно туда).
Логи: `make prod-logs s=proxy`.

---

## 7. Cloudflare: кеширование и защита

### Что кешировать нельзя

Cloudflare по умолчанию кеширует только статические расширения файлов и
не трогает ответы с `Set-Cookie`, поэтому «из коробки» приватные ответы
не кешируются. Тем не менее правила задаются явно — чтобы случайное
включение «Cache Everything» не выдало заявку одного клиента другому.

**Caching → Cache Rules**, правило `bypass-api` (выполняется первым):

```
Если  URI Path начинается с "/api/"  или  URI Path начинается с "/admin"
То    Cache eligibility: Bypass cache
```

Под это правило попадают вход в систему, кабинет клиента, создание
заявок, вся админка и обмен с 1С. Приложение дополнительно отдаёт
`Cache-Control: no-store` на `/api/v1/admin/*`, `/api/v1/customer/*`
и `/api/v1/public/auth/*` — правило в Cloudflare дублирует эту защиту,
а не заменяет её.

### Что кешировать можно

- статика Next.js (`/_next/static/*`) — неизменяемые файлы с хешем
  в имени, кешируются по заголовкам приложения;
- изображения товаров на `cdn.oinau-pro.kz` — отдаются с
  `Cache-Control: public, max-age=31536000, immutable`, потому что имя
  файла меняется вместе с содержимым.

Публичный каталог (`/api/v1/public/*`) кешируется **приложением**, а не
Cloudflare: Next.js держит ответы каталога 60 секунд, а тексты CMS —
5 минут. Этот кеш менять не нужно: он переживает перезапуск Cloudflare
и очищается сам.

### Прочие настройки

- **Speed → Optimization**: Brotli включить;
- **Security → WAF**: managed rules достаточно; режим «I'm Under Attack»
  ломает обмен с 1С — он не проходит JS-проверку;
- **Network → Upload limit**: на бесплатном тарифе 100 МБ, этого хватает
  (потолок тела запроса на прокси — 20 МБ, размер XLSX ограничен 15 МБ);
- **Network → WebSockets**: приложение их не использует, можно не
  включать.

---

## 8. Резервные копии

Скрипт есть в репозитории, но **сам он по расписанию не запускается** —
расписание нужно установить на сервере.

```bash
sudo cp infra/backup/systemd/oinau-backup.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now oinau-backup.timer
systemctl list-timers oinau-backup.timer
```

В юните проверьте `User=` и `WorkingDirectory=` — они должны
соответствовать пользователю деплоя и каталогу репозитория.

Первую копию снимите вручную и сразу проверьте восстановимость:

```bash
make prod-backup
ls -lh /var/backups/oinau
make prod-restore-verify f=/var/backups/oinau/oinau-<дата>.dump
```

`pg-restore-verify.sh` разворачивает дамп во временную базу внутри того
же контейнера PostgreSQL, сверяет ключевые таблицы и версию миграций,
затем временную базу удаляет. Рабочая база не затрагивается.

### Копия вне сервера

Копии на диске VPS защищают от ошибочного удаления данных, но не от
потери самого сервера. Настройте внешнее хранилище:

```bash
sudo apt install -y rclone
rclone config          # remote типа s3 на Cloudflare R2, отдельный бакет
```

Затем в `.env.production`:

```
BACKUP_REMOTE=r2-backup:oinau-backups
```

> Для копий заведите **отдельный бакет и отдельный ключ**. Ключ от
> `oinau-media` не должен иметь доступа к резервным копиям: иначе
> компрометация backend означает и утечку медиа, и уничтожение архива.

### Восстановление из копии

Восстановление поверх рабочей базы — ручная и осознанная операция,
скриптом не автоматизирована намеренно.

```bash
# 1. Остановить всё, кроме базы: приложение не должно писать во время восстановления.
docker compose -f infra/docker/compose.prod.yaml --env-file .env.production \
  stop backend worker web admin

# 2. Снять копию ТЕКУЩЕГО состояния — даже сломанного.
make prod-backup

# 3. Развернуть дамп.
docker compose -f infra/docker/compose.prod.yaml --env-file .env.production \
  exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" postgres \
  pg_restore --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --clean --if-exists --no-owner --no-privileges --exit-on-error < /path/to.dump

# 4. Поднять приложение и проверить готовность.
docker compose -f infra/docker/compose.prod.yaml --env-file .env.production \
  start backend worker web admin
make prod-health
```

---

## 9. Обновление версии

```bash
cd /srv/oinau-pro
git pull
make prod-backup            # перед миграциями — всегда
make prod-build
make prod-migrate
make prod-up
make prod-health
```

Правила, которые нарушать нельзя:

1. **Резервная копия снимается до миграций, а не после.** Миграция,
   удаляющая колонку, необратима: `alembic downgrade` восстановит
   структуру, но не данные.
2. **`alembic downgrade` в production не запускается.** Откат делается
   восстановлением из копии.
3. Деплой — только после зелёного CI. Автоматического деплоя из CI нет
   намеренно: выкладка на боевой сервер остаётся осознанным действием.

---

## 10. Проверка после развёртывания

```bash
make prod-ps        # все сервисы healthy
make prod-health    # postgres, redis и storage = ok
curl -sI https://oinau-pro.kz | head -20
curl -sI http://oinau-pro.kz | head -5     # должен быть редирект на https
curl -s  https://oinau-pro.kz/health
```

В браузере:

| Что      | Адрес                  | Ожидание                                    |
| -------- | ---------------------- | ------------------------------------------- |
| Витрина  | `https://oinau-pro.kz` | главная, картинки с `cdn.`                  |
| Каталог  | `/catalog`             | фильтры, поиск, пагинация                   |
| Карточка | `/product/<slug>`      | изображения, цены, форма заявки             |
| Кабинет  | `/cabinet/login`       | вход клиента                                |
| Админка  | `/admin`               | форма входа                                 |
| robots   | `/robots.txt`          | `Sitemap: https://oinau-pro.kz/sitemap.xml` |
| sitemap  | `/sitemap.xml`         | адреса на `https://oinau-pro.kz`            |

В консоли браузера не должно быть: ошибок, смешанного содержимого,
запросов на `localhost`, обращений к API по `http://`, ошибок CORS.
Проверьте ширины 390 px и 1440 px.

Отдельно — уведомления. Оставьте тестовую заявку через форму на сайте
и проверьте, что она дошла:

```bash
# Событие должно стать sent, а не остаться pending или уйти в failed.
docker compose -f infra/docker/compose.prod.yaml --env-file .env.production \
  exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "SELECT event, channel, status, attempts, left(last_error, 60) \
   FROM notification_outbox ORDER BY id DESC LIMIT 5;"
```

Сообщение должно появиться **в нужной теме** Telegram-группы, а письмо —
на адресах из `NOTIFY_EMAILS`. Типичные ответы Telegram в `last_error`:
`message thread not found` — неверный `TELEGRAM_MESSAGE_THREAD_ID`;
`chat not found` — неверный `TELEGRAM_CHAT_ID` или бот не в группе;
403 — у бота нет права писать в этой теме.

---

## 11. Что доступно снаружи

Только это:

| Порт        | Кто слушает | Зачем                        |
| ----------- | ----------- | ---------------------------- |
| 22/tcp      | sshd        | администрирование (по ключу) |
| 80/tcp      | Caddy       | редирект на HTTPS и ACME     |
| 443/tcp+udp | Caddy       | сайт                         |

Наружу **не выставлены** PostgreSQL, Redis, backend, воркер и админский
API Caddy (2019, слушает только localhost внутри контейнера). Контейнеры
базы и Redis подключены к сети `internal: true` — у них нет маршрута в
интернет даже исходящего.

Диагностический `/health/ready` наружу не отдаётся (прокси возвращает
404): он показывает, какая именно зависимость сломана. Смотреть его
следует на сервере через `make prod-health`.
