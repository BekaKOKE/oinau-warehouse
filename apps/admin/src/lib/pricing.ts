/**
 * Редактор цен: строки ступеней, проверка до отправки и превью витрины.
 *
 * Все значения — строки: из поля ввода они уходят в API через
 * normalizeDecimalInput и ни разу не превращаются в число. Проверки
 * повторяют PricingUpdate (app/modules/pricing/schemas_admin.py), чтобы
 * ошибку было видно у поля сразу; решение по-прежнему за backend.
 */

import type { PriceTierInput, PriceTierRead, PricingType, PricingUpdate } from '@/lib/api/types';
import {
  compareDecimal,
  currencySymbol,
  formatMoney,
  formatQuantity,
  normalizeDecimalInput,
} from '@/lib/decimal';
import { unitLabel } from '@/lib/format';

export const MAX_TIERS = 20;

export type TierRow = {
  /** Локальный ключ строки для React: у новых ступеней id ещё нет. */
  key: string;
  minQty: string;
  maxQty: string;
  price: string;
};

export type TierErrors = { minQty?: string; maxQty?: string; price?: string };

export type PricingValidation =
  | { ok: true; payload: PricingUpdate }
  | { ok: false; rows: Record<string, TierErrors>; form?: string };

let rowSeq = 0;
export function newTierRow(partial: Partial<Omit<TierRow, 'key'>> = {}): TierRow {
  rowSeq += 1;
  return { key: `tier-${rowSeq}`, minQty: '', maxQty: '', price: '', ...partial };
}

/** Ступени из API → строки редактора (десятичные остаются строками). */
export function rowsFromTiers(tiers: readonly PriceTierRead[]): TierRow[] {
  return tiers.map((tier) =>
    newTierRow({
      minQty: formatInput(tier.min_qty),
      maxQty: tier.max_qty ? formatInput(tier.max_qty) : '',
      price: tier.price,
    }),
  );
}

/** «10.000» → «10»: хвостовые нули количества в поле ввода не нужны. */
function formatInput(value: string): string {
  return value.includes('.') ? value.replace(/\.?0+$/, '') : value;
}

export function validatePricing(type: PricingType, rows: readonly TierRow[]): PricingValidation {
  if (type === 'ON_REQUEST') return { ok: true, payload: { pricing_type: type, tiers: [] } };

  const errors: Record<string, TierErrors> = {};
  const tiers: (PriceTierInput & { key: string; min: string; max: string | null })[] = [];

  if (type === 'FIXED') {
    const row = rows[0];
    const price = normalizeDecimalInput(row?.price ?? '', { maxFraction: 2 });
    if (!price.ok) return { ok: false, rows: { [row?.key ?? 'fixed']: { price: price.error } } };
    return {
      ok: true,
      payload: { pricing_type: type, tiers: [{ min_qty: '1', max_qty: null, price: price.value }] },
    };
  }

  if (rows.length === 0) return { ok: false, rows: {}, form: 'Добавьте хотя бы одну ступень' };
  if (rows.length > MAX_TIERS)
    return { ok: false, rows: {}, form: `Не больше ${MAX_TIERS} ступеней` };

  for (const row of rows) {
    const rowErrors: TierErrors = {};
    const min = normalizeDecimalInput(row.minQty, { maxFraction: 3, allowZero: false });
    const max = row.maxQty.trim()
      ? normalizeDecimalInput(row.maxQty, { maxFraction: 3, allowZero: false })
      : null;
    const price = normalizeDecimalInput(row.price, { maxFraction: 2 });
    if (!min.ok) rowErrors.minQty = min.error;
    if (max && !max.ok) rowErrors.maxQty = max.error;
    if (!price.ok) rowErrors.price = price.error;
    if (min.ok && max?.ok && compareDecimal(max.value, min.value) < 0) {
      rowErrors.maxQty = 'Меньше, чем «от»';
    }
    if (Object.keys(rowErrors).length > 0) {
      errors[row.key] = rowErrors;
      continue;
    }
    if (min.ok && price.ok && (!max || max.ok)) {
      const maxValue = max && max.ok ? max.value : null;
      tiers.push({
        key: row.key,
        min: min.value,
        max: maxValue,
        min_qty: min.value,
        max_qty: maxValue,
        price: price.value,
      });
    }
  }
  if (Object.keys(errors).length > 0) return { ok: false, rows: errors };

  if (tiers.filter((tier) => tier.max === null).length > 1) {
    return { ok: false, rows: {}, form: 'Открытая ступень («и более») может быть только одна' };
  }
  // Границы включающие, как numrange '[]' в базе: 1–10 и 10–20 пересекаются.
  const ordered = [...tiers].sort((a, b) => compareDecimal(a.min, b.min));
  for (let index = 1; index < ordered.length; index += 1) {
    const previous = ordered[index - 1];
    const current = ordered[index];
    if (!previous || !current) continue;
    if (previous.max === null || compareDecimal(previous.max, current.min) >= 0) {
      return {
        ok: false,
        rows: {
          [current.key]: { minQty: `Пересекается со ступенью от ${formatQuantity(previous.min)}` },
        },
      };
    }
  }

  return {
    ok: true,
    payload: {
      pricing_type: type,
      tiers: ordered.map(({ min_qty, max_qty, price }) => ({ min_qty, max_qty, price })),
    },
  };
}

// ---------------------------------------------------------------- превью

export type PricePreview = {
  /** Строка, как в карточке каталога: «3 500 ₸ / м», «от 2 600 ₸ / шт». */
  headline: string;
  /** Таблица ступеней — для TIERED, как в карточке товара на витрине. */
  table: { range: string; price: string }[];
};

export function tierRange(min: string, max: string | null | undefined): string {
  const from = formatQuantity(min);
  return max ? `${from}–${formatQuantity(max)}` : `${from} и более`;
}

/**
 * Как цену увидит посетитель. Правила совпадают с describePrice витрины
 * (apps/web/src/lib/format.ts): FIXED — сумма за единицу, FROM и TIERED —
 * «от» минимальной ступени, ON_REQUEST и отсутствие ступеней — запрос.
 */
export function previewPrice(payload: PricingUpdate, unit: string, currency: string): PricePreview {
  const tiers = payload.tiers ?? [];
  const perUnit = `${currencySymbol(currency)} / ${unitLabel(unit)}`;
  if (payload.pricing_type === 'ON_REQUEST' || tiers.length === 0) {
    return { headline: 'Цена по запросу', table: [] };
  }
  const prices = tiers.map((tier) => String(tier.price));
  const min = prices.reduce((best, value) => (compareDecimal(value, best) < 0 ? value : best));
  if (payload.pricing_type === 'FIXED') {
    return { headline: `${formatMoney(String(tiers[0]?.price))} ${perUnit}`, table: [] };
  }
  const headline = `от ${formatMoney(min)} ${perUnit}`;
  if (payload.pricing_type === 'FROM') return { headline, table: [] };
  return {
    headline,
    table: tiers.map((tier) => ({
      range: tierRange(
        String(tier.min_qty),
        tier.max_qty === null || tier.max_qty === undefined ? null : String(tier.max_qty),
      ),
      price: formatMoney(String(tier.price), currency),
    })),
  };
}

/** Короткая цена для строки списка: «3 500 ₸», «от 2 600 ₸», «По запросу». */
export function listPrice(
  type: PricingType,
  minPrice: string | null | undefined,
  currency: string | null | undefined,
): string {
  if (type === 'ON_REQUEST') return 'По запросу';
  if (!minPrice) return 'Нет цены';
  if (type === 'FIXED') return formatMoney(minPrice, currency ?? undefined);
  return `от ${formatMoney(minPrice, currency ?? undefined)}`;
}
