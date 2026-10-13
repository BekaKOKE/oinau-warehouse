/**
 * Поля разделов CMS: локализованный текст, ссылки, телефоны, реквизиты.
 *
 * Проверки повторяют типы backend (app/modules/content/fields.py,
 * app/core/text.py), чтобы сотрудник видел ошибку у поля до отправки.
 * Источник истины всё равно backend: его 422 раскладывается по тем же
 * путям полей («hero.title», «faq.items.3.answer»).
 */

import type { FieldErrors } from '@/lib/errors';

export const DEFAULT_LOCALE = 'ru';
/** Казахская версия: структура есть, заполнять необязательно. */
export const EXTRA_LOCALE = 'kk';

/** Локализованный текст в форме — как в API: {"ru": "...", "kk": "..."}. */
export type Loc = Record<string, string>;

export type TextKind = 'line' | 'question' | 'seo' | 'short' | 'text';

/** Пределы длины — LocalizedLine/Question/SeoText/ShortText/Text. */
export const TEXT_LIMITS: Record<TextKind, number> = {
  line: 255,
  question: 500,
  seo: 500,
  short: 1000,
  text: 5000,
};

export const TEXT_MULTILINE: Record<TextKind, boolean> = {
  line: false,
  question: false,
  seo: false,
  short: true,
  text: true,
};

export const URL_MAX_LENGTH = 1000;
export const PHONE_MAX_LENGTH = 32;
export const EMAIL_MAX_LENGTH = 255;

/** Ссылка на файл медиатеки внутри раздела: путь поля и UUID. */
export type MediaRef = { path: string; uuid: string };

// ------------------------------------------------------------ ключи списков

let sequence = 0;

/** Ключ элемента списка в форме (React key); в API не уходит. */
export function newUid(): string {
  sequence += 1;
  return `row-${sequence}`;
}

// ------------------------------------------------------------ локализация

export function locFrom(value: Record<string, string> | null | undefined): Loc {
  return value ? { ...value } : {};
}

function normalizeText(value: string): string {
  return value.replace(/\r\n?/g, '\n').trim();
}

export function isLocEmpty(value: Loc): boolean {
  return Object.values(value).every((text) => normalizeText(text) === '');
}

/** Для необязательного поля: пустой текст — `null`, а не `{}` (backend требует ru). */
export function locOut(value: Loc): Record<string, string> | null {
  const result: Record<string, string> = {};
  for (const [locale, text] of Object.entries(value)) {
    const clean = normalizeText(text);
    if (clean) result[locale] = clean;
  }
  return Object.keys(result).length > 0 ? result : null;
}

/** Для обязательного поля; наличие ru гарантирует проверка формы. */
export function locRequired(value: Loc): Record<string, string> {
  return locOut(value) ?? {};
}

// Начало тега по правилам HTML — то же выражение, что в app/core/text.py.
const TAG_PATTERN = /<[/!?A-Za-z]/;

function charLength(value: string): number {
  return Array.from(value).length;
}

export function textError(value: string, kind: TextKind): string | null {
  const text = normalizeText(value);
  if (!TEXT_MULTILINE[kind] && text.includes('\n')) return 'Перевод строки в этом поле недопустим';
  if (TAG_PATTERN.test(text)) return 'HTML-разметка не допускается: поле хранит простой текст';
  const limit = TEXT_LIMITS[kind];
  if (charLength(text) > limit) return `Текст длиннее ${limit} символов`;
  return null;
}

/**
 * Ошибки локализованного поля. Ошибка русской версии — под ключом поля,
 * других языков — `путь.локаль`.
 */
export function validateLoc(
  errors: FieldErrors,
  path: string,
  value: Loc,
  kind: TextKind,
  { required = false }: { required?: boolean } = {},
): void {
  for (const [locale, text] of Object.entries(value)) {
    const error = textError(text, kind);
    if (error) errors[locale === DEFAULT_LOCALE ? path : `${path}.${locale}`] = error;
  }
  if (errors[path]) return;
  const ru = normalizeText(value[DEFAULT_LOCALE] ?? '');
  if (ru) return;
  if (required) errors[path] = 'Заполните текст на русском';
  else if (!isLocEmpty(value)) {
    errors[path] = 'Заполните русскую версию: без неё перевод не сохранится';
  }
}

// ----------------------------------------------------------------- строки

export function isBlank(value: string): boolean {
  return value.trim() === '';
}

/** Ссылка кнопки: http(s)-адрес или путь на своём сайте (`/catalog`). */
export function linkError(value: string): string | null {
  const link = value.trim();
  if (!link) return 'Укажите ссылку';
  if (/\s/.test(link)) return 'Ссылка не может содержать пробелы';
  if (charLength(link) > URL_MAX_LENGTH) return `Ссылка длиннее ${URL_MAX_LENGTH} символов`;
  if (link.startsWith('//')) return 'Протокол-относительные ссылки (//host) не допускаются';
  if (link.startsWith('/')) return null;
  return absoluteUrlError(link, true);
}

/** Ссылка на соцсеть — только https. */
export function httpsUrlError(value: string): string | null {
  const link = value.trim();
  if (!link) return 'Укажите ссылку';
  if (/\s/.test(link)) return 'Ссылка не может содержать пробелы';
  if (charLength(link) > URL_MAX_LENGTH) return `Ссылка длиннее ${URL_MAX_LENGTH} символов`;
  return absoluteUrlError(link, false);
}

function absoluteUrlError(link: string, allowHttp: boolean): string | null {
  const message = allowHttp
    ? 'Допустимы только ссылки https://, http:// или путь /...'
    : 'Допустимы только ссылки https://';
  let url: URL;
  try {
    url = new URL(link);
  } catch {
    return message;
  }
  const schemes = allowHttp ? ['https:', 'http:'] : ['https:'];
  if (!schemes.includes(url.protocol)) return message;
  if (!url.hostname || url.username || url.password) return 'Некорректный адрес ссылки';
  return null;
}

/** Телефон — то же правило, что в заявках (normalize_phone). */
export function phoneError(value: string): string | null {
  const phone = value.trim().replace(/\s+/g, ' ');
  if (!phone) return 'Укажите номер';
  if (phone.length > PHONE_MAX_LENGTH) return `Номер длиннее ${PHONE_MAX_LENGTH} символов`;
  if (!/^\+?[0-9\s\-()]+$/.test(phone)) {
    return 'Телефон может содержать только цифры, пробелы, «+», «-» и скобки';
  }
  const digits = phone.replace(/\D/g, '').length;
  if (digits < 5 || digits > 15) return 'В номере телефона должно быть от 5 до 15 цифр';
  return null;
}

export function emailError(value: string): string | null {
  const email = value.trim();
  if (!email) return 'Укажите email';
  if (email.length > EMAIL_MAX_LENGTH) return `Email длиннее ${EMAIL_MAX_LENGTH} символов`;
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return 'Некорректный email';
  return null;
}

/** Координата: запятая допустима как десятичный разделитель. */
export function parseCoordinate(value: string): number | null {
  const text = value.trim().replace(',', '.');
  if (!/^-?\d+(\.\d+)?$/.test(text)) return null;
  return Number(text);
}

export function coordinateError(value: string, limit: 90 | 180): string | null {
  const number = parseCoordinate(value);
  if (number === null) return 'Число, например 43.238949';
  if (Math.abs(number) > limit) return `От −${limit} до ${limit}`;
  return null;
}

// -------------------------------------------------------------- реквизиты

/** Реквизиты хранятся без пробелов и в верхнем регистре — как их приводит backend. */
export function compactUpper(value: string): string {
  return value.replace(/\s+/g, '').toUpperCase();
}

export function binError(value: string): string | null {
  return /^\d{12}$/.test(compactUpper(value)) ? null : 'БИН/ИИН — 12 цифр';
}

export function bikError(value: string): string | null {
  return /^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$/.test(compactUpper(value))
    ? null
    : 'БИК (SWIFT) — 8 или 11 знаков';
}

export function kbeError(value: string): string | null {
  return /^\d{2}$/.test(compactUpper(value)) ? null : 'КБе — 2 цифры';
}

/** IBAN Казахстана с проверкой контрольной суммы (ISO 13616, mod 97). */
export function ibanError(value: string): string | null {
  const iban = compactUpper(value);
  if (!/^KZ\d{2}[A-Z0-9]{16}$/.test(iban)) return 'IBAN должен иметь вид KZ + 18 знаков';
  const rearranged = iban.slice(4) + iban.slice(0, 4);
  // Остаток считается по частям: число из 40+ цифр не помещается в Number.
  let remainder = 0;
  for (const char of rearranged) {
    const digits = Number.parseInt(char, 36).toString();
    for (const digit of digits) remainder = (remainder * 10 + Number(digit)) % 97;
  }
  return remainder === 1 ? null : 'Неверная контрольная сумма IBAN';
}

// ---------------------------------------------------------- сравнение форм

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value)
        // Ключ строки списка и пустой перевод не меняют данные раздела.
        .filter(([name, item]) => name !== 'uid' && item !== '')
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .map(([name, item]) => [name, canonical(item)]),
    );
  }
  return value;
}

/** Совпадают ли две формы по содержанию (порядок ключей и uid не важны). */
export function sameForm(a: unknown, b: unknown): boolean {
  return JSON.stringify(canonical(a)) === JSON.stringify(canonical(b));
}

/** Заполнен ли где-нибудь в форме казахский перевод. */
export function hasExtraLocale(value: unknown): boolean {
  if (Array.isArray(value)) return value.some(hasExtraLocale);
  if (value !== null && typeof value === 'object') {
    return Object.entries(value).some(
      ([name, item]) =>
        (name === EXTRA_LOCALE && typeof item === 'string' && item.trim() !== '') ||
        hasExtraLocale(item),
    );
  }
  return false;
}
