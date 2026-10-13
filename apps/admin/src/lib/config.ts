/**
 * Конфигурация админки.
 *
 * Все запросы к API админка делает из браузера: access-токен живёт
 * только в памяти вкладки, и серверу Next.js передать его нечем.
 * Поэтому нужен один адрес — публичный.
 */

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

/** Префикс маршрутов приложения (совпадает с `basePath` в next.config.ts). */
export const BASE_PATH = '/admin';

/** Адрес витрины — ссылки «открыть на сайте». */
export const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? 'http://localhost:3000';
