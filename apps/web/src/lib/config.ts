/**
 * Конфигурация витрины.
 *
 * Всё, что зависит от окружения, читается здесь и только здесь.
 * В браузер попадают ТОЛЬКО переменные с префиксом NEXT_PUBLIC_ —
 * Next.js встраивает в бандл именно их, поэтому секретов среди них
 * быть не может.
 */

/** Адрес API, по которому в браузер уходят клиентские запросы. */
export const PUBLIC_API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

/**
 * Адрес API для запросов с сервера Next.js.
 *
 * В Docker контейнер web не видит `localhost:8000` хоста, зато видит
 * `backend:8000`. Отдельная переменная избавляет от необходимости
 * выбирать адрес в коде компонента.
 */
export const SERVER_API_URL =
  process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

/** Канонический адрес сайта — нужен метаданным и OpenGraph. */
export const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? 'http://localhost:3000';

/**
 * Номер WhatsApp для плавающей кнопки.
 *
 * Значение по умолчанию нужно лишь для локального запуска без CMS:
 * если в CMS заполнены контакты, ссылка берётся оттуда.
 */
export const WHATSAPP_NUMBER = process.env.NEXT_PUBLIC_WHATSAPP_NUMBER ?? '+77270000000';

export const WHATSAPP_MESSAGE =
  process.env.NEXT_PUBLIC_WHATSAPP_MESSAGE ?? 'Здравствуйте! Пишу с сайта OINAU PRO.';

export function whatsappLink(number: string, message: string): string {
  const digits = number.replace(/\D/g, '');
  return `https://wa.me/${digits}?text=${encodeURIComponent(message)}`;
}

/** Запасное название сайта, пока раздел настроек CMS не заполнен. */
export const SITE_NAME = 'OINAU PRO';
export const SITE_TAGLINE = 'Комплектующие для детских и спортивных площадок';

/** Сколько товаров показывает страница каталога. */
/**
 * Строк на странице таблицы товаров раздела. Совпадает с потолком
 * API (MAX_PAGE_SIZE = 60): B2B-покупатель сравнивает много позиций
 * сразу, а дальше — «Показать ещё» или страницы.
 */
export const TABLE_PAGE_SIZE = 60;

export const CATALOG_PAGE_SIZE = 24;
