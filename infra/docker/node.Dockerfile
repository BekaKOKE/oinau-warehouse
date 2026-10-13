# syntax=docker/dockerfile:1.7
# Общий образ для apps/web и apps/admin.
# Контекст сборки — корень монорепозитория (нужен доступ к packages/*).
#
# Аргументы:
#   APP_PATH    — apps/web  | apps/admin
#   APP_PACKAGE — @oinau/web | @oinau/admin

FROM node:22-alpine AS base
RUN corepack enable
WORKDIR /repo
ENV NEXT_TELEMETRY_DISABLED=1

# ------------------------------------------------------------------ development
FROM base AS development
# Код монтируется томом, зависимости ставятся при старте контейнера.
CMD ["sh", "-c", "pnpm install --frozen-lockfile && pnpm --filter ${APP_PACKAGE} dev"]

# --------------------------------------------------------------------- builder
FROM base AS builder
ARG APP_PATH
ARG APP_PACKAGE
COPY pnpm-workspace.yaml package.json pnpm-lock.yaml* ./
COPY packages ./packages
# Манифесты ОБОИХ приложений: pnpm-lock.yaml описывает весь workspace,
# и с --frozen-lockfile установка падает, если проект из lock-файла
# отсутствует в дереве. Слой при этом общий для обоих образов.
COPY apps/web/package.json ./apps/web/package.json
COPY apps/admin/package.json ./apps/admin/package.json
RUN pnpm install --frozen-lockfile
COPY ${APP_PATH} ./${APP_PATH}
# standalone собирается только здесь: production-образ берёт из него
# server.js, а локальной сборке этот режим не нужен (см. next.config.ts).
ENV NEXT_BUILD_STANDALONE=1
# NEXT_PUBLIC_* объявлены именно здесь, в стадии сборки: build-arg, не
# объявленный через ARG в той стадии, где он нужен, docker молча
# игнорирует. Без этих строк `next build` не видел переменных и зашивал
# в браузерный бандл значения по умолчанию из src/lib/config.ts
# (http://localhost:8000). Объявление стоит после установки зависимостей,
# чтобы смена адреса не инвалидировала слой с pnpm install.
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_SITE_URL
ARG NEXT_PUBLIC_CDN_BASE_URL
ARG NEXT_PUBLIC_WHATSAPP_NUMBER
ARG NEXT_PUBLIC_WHATSAPP_MESSAGE
# Пустое значение — не то же самое, что отсутствующее: `?? 'значение по
# умолчанию'` в config.ts на пустую строку не сработает. Поэтому
# необязательные переменные, пришедшие пустыми, убираются из окружения,
# а обязательные проваливают сборку сразу, а не в браузере у клиента.
RUN set -eu; \
    : "${NEXT_PUBLIC_API_URL:?build-arg NEXT_PUBLIC_API_URL obyazatelen}"; \
    : "${NEXT_PUBLIC_SITE_URL:?build-arg NEXT_PUBLIC_SITE_URL obyazatelen}"; \
    [ -n "${NEXT_PUBLIC_CDN_BASE_URL:-}" ] || unset NEXT_PUBLIC_CDN_BASE_URL; \
    [ -n "${NEXT_PUBLIC_WHATSAPP_NUMBER:-}" ] || unset NEXT_PUBLIC_WHATSAPP_NUMBER; \
    [ -n "${NEXT_PUBLIC_WHATSAPP_MESSAGE:-}" ] || unset NEXT_PUBLIC_WHATSAPP_MESSAGE; \
    pnpm --filter "${APP_PACKAGE}" build

# ------------------------------------------------------------------ production
FROM base AS production
ARG APP_PATH
# APP_DIR остаётся в окружении: CMD запускает server.js по этому пути.
ENV NODE_ENV=production \
    APP_DIR=${APP_PATH} \
    PORT=3000 \
    HOSTNAME=0.0.0.0
RUN addgroup -g 10001 app && adduser -u 10001 -G app -D app
# В монорепозитории Next кладёт standalone с сохранением структуры:
# .next/standalone/<APP_PATH>/server.js + общий node_modules в корне.
# Поэтому копируем в /repo, а запускаем /repo/<APP_PATH>/server.js.
COPY --from=builder --chown=app:app /repo/${APP_PATH}/.next/standalone ./
COPY --from=builder --chown=app:app /repo/${APP_PATH}/.next/static ./${APP_PATH}/.next/static
COPY --from=builder --chown=app:app /repo/${APP_PATH}/public ./${APP_PATH}/public
USER app
EXPOSE 3000
# Проверяется только то, что сервер Next принимает соединения.
# Запрашивать страницу нельзя: она ходит в API и в CMS, и недоступность
# backend выглядела бы как падение самой витрины — прокси снял бы
# с балансировки живой контейнер.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD node -e "require('net').connect(+process.env.PORT||3000,'127.0.0.1').on('connect',function(){this.end();process.exit(0)}).on('error',()=>process.exit(1)).setTimeout(4000,()=>process.exit(1))"
CMD ["sh", "-c", "exec node ${APP_DIR}/server.js"]
