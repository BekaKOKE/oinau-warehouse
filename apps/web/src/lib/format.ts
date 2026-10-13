/**
 * Форматирование чисел, цен и единиц измерения.
 *
 * Деньги и количества приходят из API строками: backend отдаёт
 * NUMERIC как строку, чтобы не терять точность на числе с плавающей
 * точкой. Здесь они и остаются строками — в арифметику витрина их
 * не пускает, цену считает сервер.
 */

import type { PriceInfo, PublicAvailability } from '@oinau/api-types';

const CURRENCY_SYMBOLS: Record<string, string> = {
  KZT: '₸',
  RUB: '₽',
  USD: '$',
  EUR: '€',
};

const UNIT_LABELS: Record<string, string> = {
  pcs: 'шт',
  m: 'м',
  m2: 'м²',
  kg: 'кг',
  set: 'компл',
  pack: 'упак',
  l: 'л',
};

export function currencySymbol(code: string): string {
  return CURRENCY_SYMBOLS[code] ?? code;
}

export function unitLabel(unit: string): string {
  return UNIT_LABELS[unit] ?? unit;
}

/** «3500.00» → «3 500». Хвостовые нули в цене на витрине лишние. */
export function formatAmount(value: string): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return value;
  return new Intl.NumberFormat('ru-RU', {
    minimumFractionDigits: 0,
    maximumFractionDigits: Number.isInteger(numeric) ? 0 : 2,
  }).format(numeric);
}

/** «5.000» → «5», «2.500» → «2,5». Количество бывает дробным (канат). */
export function formatQuantity(value: string): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return value;
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 }).format(numeric);
}

export function formatCount(value: number): string {
  return new Intl.NumberFormat('ru-RU').format(value);
}

/** «12 товаров» / «1 товар» / «3 товара». */
export function plural(count: number, forms: [string, string, string]): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return forms[0];
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return forms[1];
  return forms[2];
}

export function productCountLabel(count: number): string {
  return `${formatCount(count)} ${plural(count, ['товар', 'товара', 'товаров'])}`;
}

// ------------------------------------------------------------------ цены

export type PriceDisplay = {
  /** Готовая строка: «3 500 ₸ / м», «от 2 600 ₸», «Цена по запросу». */
  label: string;
  /** Приставка «от» выводится отдельным мелким шрифтом. */
  prefix?: string;
  /** Сумма без единицы — для крупного начертания. */
  amount?: string;
  /** «₸ / м». */
  suffix?: string;
  /** Цены нет: показываем кнопку запроса вместо суммы. */
  onRequest: boolean;
};

/**
 * Публичное представление цены по правилам backend.
 *
 * FIXED       — «X ₸ / шт»
 * FROM        — «от X ₸»
 * TIERED      — «от X ₸», таблица ступеней открывается в карточке
 * ON_REQUEST  — «Цена по запросу»
 *
 * Цена никогда не выдумывается: если сервер не прислал сумму, показывается
 * запрос, а не ноль.
 */
export function describePrice(price: PriceInfo, unit: string): PriceDisplay {
  const symbol = currencySymbol(price.currency);

  if (price.type === 'ON_REQUEST') {
    return { label: 'Цена по запросу', onRequest: true };
  }

  if (price.type === 'FIXED' && price.price) {
    const amount = formatAmount(price.price);
    const suffix = `${symbol} / ${unitLabel(unit)}`;
    return { label: `${amount} ${suffix}`, amount, suffix, onRequest: false };
  }

  if (price.from_price) {
    const amount = formatAmount(price.from_price);
    const suffix = `${symbol} / ${unitLabel(unit)}`;
    return {
      label: `от ${amount} ${suffix}`,
      prefix: 'от',
      amount,
      suffix,
      onRequest: false,
    };
  }

  return { label: 'Цена по запросу', onRequest: true };
}

/**
 * Оптовая ступень для карточки каталога: «от 50 м — 2 600 ₸».
 *
 * Берётся самая крупная ступень из прайса товара. Нет ступеней (цена
 * фиксированная или по запросу) — строки нет, выдумывать скидку нельзя.
 */
export function describeWholesale(price: PriceInfo, unit: string): string | null {
  const tiers = price.tiers ?? [];
  if (tiers.length < 2) return null;
  const top = tiers.reduce((best, tier) =>
    Number(tier.min_quantity) > Number(best.min_quantity) ? tier : best,
  );
  return (
    `от ${formatQuantity(top.min_quantity)} ${unitLabel(unit)} — ` +
    `${formatAmount(top.price)} ${currencySymbol(price.currency)}`
  );
}

// -------------------------------------------------------------- наличие

export type AvailabilityDisplay = {
  label: string;
  tone: 'success' | 'warning' | 'muted';
};

export const AVAILABILITY: Record<PublicAvailability, AvailabilityDisplay> = {
  IN_STOCK: { label: 'В наличии', tone: 'success' },
  ON_REQUEST: { label: 'Под заказ', tone: 'warning' },
  OUT_OF_STOCK: { label: 'Нет в наличии', tone: 'muted' },
};

export function describeAvailability(value: PublicAvailability): AvailabilityDisplay {
  return AVAILABILITY[value] ?? AVAILABILITY.ON_REQUEST;
}

/** Диапазон ступени: «1–49», «500 и более». */
export function formatTierRange(min: string, max: string | null | undefined): string {
  const from = formatQuantity(min);
  return max ? `${from}–${formatQuantity(max)}` : `${from} и более`;
}
