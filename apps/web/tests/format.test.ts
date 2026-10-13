/**
 * Правила показа цены и наличия — самая чувствительная логика витрины.
 * Придуманная цена в B2B-каталоге дороже любой другой ошибки.
 */

import { describe, expect, it } from 'vitest';

import {
  describeAvailability,
  describePrice,
  formatAmount,
  formatQuantity,
  formatTierRange,
  plural,
  productCountLabel,
  unitLabel,
} from '@/lib/format';
import { fixedPrice, fromPrice, onRequestPrice, tieredPrice } from './factories';

// Intl для ru-RU разделяет разряды НЕРАЗРЫВНЫМ пробелом: цена не должна
// переноситься на другую строку посреди числа.
const NBSP = ' ';

describe('describePrice', () => {
  it('FIXED показывает цену с единицей измерения', () => {
    const result = describePrice(fixedPrice, 'pcs');
    expect(result.onRequest).toBe(false);
    expect(result.amount).toBe(`15${NBSP}900`);
    expect(result.suffix).toBe('₸ / шт');
    expect(result.prefix).toBeUndefined();
  });

  it('FROM показывает минимальную цену с приставкой «от»', () => {
    const result = describePrice(fromPrice, 'm');
    expect(result.prefix).toBe('от');
    expect(result.amount).toBe(`2${NBSP}800`);
    expect(result.label).toBe(`от 2${NBSP}800 ₸ / м`);
  });

  it('TIERED показывает «от» по минимальной ступени', () => {
    const result = describePrice(tieredPrice, 'm');
    expect(result.prefix).toBe('от');
    expect(result.amount).toBe(`2${NBSP}600`);
    expect(result.onRequest).toBe(false);
  });

  it('ON_REQUEST не показывает сумму', () => {
    const result = describePrice(onRequestPrice, 'pcs');
    expect(result.onRequest).toBe(true);
    expect(result.label).toBe('Цена по запросу');
    expect(result.amount).toBeUndefined();
  });

  it('без суммы от сервера цена не выдумывается', () => {
    // Тип обещает цену, но значений нет — показываем запрос, а не ноль.
    const broken = { ...fixedPrice, price: null, from_price: null };
    expect(describePrice(broken, 'pcs').onRequest).toBe(true);
  });
});

describe('describeAvailability', () => {
  it('переводит статусы backend', () => {
    expect(describeAvailability('IN_STOCK')).toEqual({ label: 'В наличии', tone: 'success' });
    expect(describeAvailability('ON_REQUEST')).toEqual({ label: 'Под заказ', tone: 'warning' });
    expect(describeAvailability('OUT_OF_STOCK')).toEqual({
      label: 'Нет в наличии',
      tone: 'muted',
    });
  });
});

describe('форматирование чисел', () => {
  it('убирает хвостовые нули денежной строки', () => {
    expect(formatAmount('3500.00')).toBe(`3${NBSP}500`);
    expect(formatAmount('320.50')).toBe('320,5');
  });

  it('форматирует дробное количество', () => {
    expect(formatQuantity('5.000')).toBe('5');
    expect(formatQuantity('2.500')).toBe('2,5');
  });

  it('склоняет слово «товар»', () => {
    expect(plural(1, ['товар', 'товара', 'товаров'])).toBe('товар');
    expect(plural(3, ['товар', 'товара', 'товаров'])).toBe('товара');
    expect(plural(11, ['товар', 'товара', 'товаров'])).toBe('товаров');
    expect(productCountLabel(21)).toBe('21 товар');
  });

  it('переводит единицы измерения', () => {
    expect(unitLabel('m')).toBe('м');
    expect(unitLabel('pcs')).toBe('шт');
    // Неизвестная единица из 1С выводится как есть, а не теряется.
    expect(unitLabel('rulon')).toBe('rulon');
  });

  it('описывает диапазон ступени', () => {
    expect(formatTierRange('1.000', '49.000')).toBe('1–49');
    expect(formatTierRange('500.000', null)).toBe('500 и более');
  });
});
