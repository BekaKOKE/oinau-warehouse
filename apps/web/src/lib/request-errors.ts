/**
 * Ошибки отправки заявки, привязанные к позициям.
 *
 * `product_unavailable` и `quantity_below_minimum` backend возвращает
 * с подробностями в `details`: артикулы и минимальные партии. Показать
 * их общим текстом мало — посетитель должен увидеть, что именно
 * исправить, поэтому подробности разворачиваются в текст.
 *
 * Обычный модуль, а не часть формы: этим заняты и корзина
 * (`RequestForm`), и окно быстрого заказа (`QuickOrderDialog`), а
 * функцию, экспортированную из `'use client'`, второй такой модуль
 * получить не может — см. `request-line.ts`.
 */

import { ApiError, describeError } from '@/lib/api/client';
import { formatQuantity } from '@/lib/format';

/** Слишком частые обращения — один текст на все формы сайта. */
const RATE_LIMITED =
  'Слишком много заявок с этого адреса. Попробуйте позже или напишите в WhatsApp.';

type MinimumItem = { sku: string; min_order_qty: string };

/** Позиции ниже минимальной партии из `details.items`. */
function belowMinimumItems(error: ApiError): MinimumItem[] {
  const items = error.details?.items;
  if (error.code !== 'quantity_below_minimum' || !Array.isArray(items)) return [];
  return items
    .filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null)
    .map((item) => ({
      sku: String(item.sku),
      min_order_qty: formatQuantity(String(item.min_order_qty)),
    }));
}

export function describeItemError(error: ApiError): string {
  const details = error.details ?? {};
  if (error.code === 'product_unavailable' && Array.isArray(details.skus)) {
    return `${error.message}: ${details.skus.join(', ')}. Уберите эти позиции из заявки.`;
  }
  const below = belowMinimumItems(error);
  if (below.length > 0) {
    const parts = below.map((item) => `${item.sku} — минимум ${item.min_order_qty}`);
    return `${error.message}: ${parts.join('; ')}`;
  }
  if (error.code === 'rate_limited') return RATE_LIMITED;
  return describeError(error);
}

/**
 * Минимальная партия для подсказки у поля количества.
 *
 * Только когда позиция одна: это «заказ в 1 клик», где поле количества
 * тоже одно и его есть чем подсветить. В корзине позиций много, и
 * общего поля количества у них нет — там достаточно текста ошибки.
 */
export function minimumFromError(error: ApiError): string | null {
  const below = belowMinimumItems(error);
  return below.length === 1 && below[0] ? below[0].min_order_qty : null;
}
