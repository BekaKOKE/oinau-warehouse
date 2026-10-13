/**
 * Даты, счётчики и склонения.
 *
 * Все метки времени backend хранит и отдаёт в UTC. Сотрудники работают
 * в Казахстане, поэтому показ — в Asia/Almaty независимо от часового
 * пояса компьютера: иначе у менеджера в командировке заявка «сдвинется».
 */

export const TIME_ZONE = 'Asia/Almaty';

const dateTimeFormat = new Intl.DateTimeFormat('ru-RU', {
  timeZone: TIME_ZONE,
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
});

const dateFormat = new Intl.DateTimeFormat('ru-RU', {
  timeZone: TIME_ZONE,
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
});

function toDate(value: string | Date): Date | null {
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—';
  const date = toDate(value);
  return date ? dateTimeFormat.format(date) : value;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  const date = toDate(value);
  return date ? dateFormat.format(date) : value;
}

/** «только что», «5 мин назад», «3 ч назад», дальше — дата. */
export function formatRelative(value: string | null | undefined, now: Date = new Date()): string {
  if (!value) return '—';
  const date = toDate(value);
  if (!date) return value;
  const minutes = Math.floor((now.getTime() - date.getTime()) / 60_000);
  if (minutes < 1) return 'только что';
  if (minutes < 60) return `${minutes} мин назад`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} ч назад`;
  return formatDateTime(value);
}

export function formatCount(value: number): string {
  return new Intl.NumberFormat('ru-RU').format(value);
}

/** plural(3, ['товар', 'товара', 'товаров']) → «товара». */
export function plural(count: number, forms: readonly [string, string, string]): string {
  const mod10 = Math.abs(count) % 10;
  const mod100 = Math.abs(count) % 100;
  if (mod10 === 1 && mod100 !== 11) return forms[0];
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return forms[1];
  return forms[2];
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} КБ`;
  return `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} МБ`;
}

const UNIT_LABELS: Record<string, string> = {
  pcs: 'шт',
  m: 'м',
  m2: 'м²',
  kg: 'кг',
  set: 'компл',
  pack: 'упак',
  l: 'л',
};

export function unitLabel(unit: string): string {
  return UNIT_LABELS[unit] ?? unit;
}
