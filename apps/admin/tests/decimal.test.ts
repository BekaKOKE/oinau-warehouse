/**
 * Десятичные значения: показ и ввод без чисел с плавающей точкой.
 */

import { describe, expect, it } from 'vitest';

import {
  compareDecimal,
  formatDecimal,
  formatMoney,
  formatQuantity,
  normalizeDecimalInput,
} from '@/lib/decimal';

const NBSP = ' ';

describe('formatDecimal / formatMoney / formatQuantity', () => {
  it('группирует разряды и ставит запятую', () => {
    expect(formatDecimal('1234567.89')).toBe(`1${NBSP}234${NBSP}567,89`);
  });

  it('не теряет точность на значениях, которые float не представляет', () => {
    // 0.1 + 0.2 и длинные значения — ровно то, что ломает Number.
    expect(formatDecimal('0.30000000000000004')).toBe('0,30000000000000004');
    expect(formatDecimal('99999999999999.99')).toBe(
      `99${NBSP}999${NBSP}999${NBSP}999${NBSP}999,99`,
    );
  });

  it('деньги: копейки только если они есть', () => {
    expect(formatMoney('3500.00', 'KZT')).toBe(`3${NBSP}500${NBSP}₸`);
    expect(formatMoney('3500.5', 'KZT')).toBe(`3${NBSP}500,50${NBSP}₸`);
    expect(formatMoney(null)).toBe('—');
  });

  it('количество без хвостовых нулей', () => {
    expect(formatQuantity('5.000')).toBe('5');
    expect(formatQuantity('2.500')).toBe('2,5');
    expect(formatQuantity('0.000')).toBe('0');
  });

  it('нечисловая строка возвращается как есть', () => {
    expect(formatDecimal('abc')).toBe('abc');
  });
});

describe('normalizeDecimalInput', () => {
  it('принимает запятую и пробелы-разделители', () => {
    expect(normalizeDecimalInput('3 500,5', { maxFraction: 2 })).toEqual({
      ok: true,
      value: '3500.5',
    });
    expect(normalizeDecimalInput('010.10', { maxFraction: 2 })).toEqual({
      ok: true,
      value: '10.1',
    });
  });

  it('отвергает лишние знаки, а не округляет', () => {
    const result = normalizeDecimalInput('10.005', { maxFraction: 2 });
    expect(result.ok).toBe(false);
  });

  it('отвергает отрицательные, мусор и ноль там, где он запрещён', () => {
    expect(normalizeDecimalInput('-1', { maxFraction: 2 }).ok).toBe(false);
    expect(normalizeDecimalInput('1e3', { maxFraction: 2 }).ok).toBe(false);
    expect(normalizeDecimalInput('', { maxFraction: 2 }).ok).toBe(false);
    expect(normalizeDecimalInput('0', { maxFraction: 3, allowZero: false }).ok).toBe(false);
  });

  it('проверяет общее число разрядов NUMERIC(14,2)', () => {
    expect(normalizeDecimalInput('999999999999', { maxFraction: 2 }).ok).toBe(true);
    expect(normalizeDecimalInput('9999999999999', { maxFraction: 2 }).ok).toBe(false);
  });
});

describe('compareDecimal', () => {
  it('сравнивает по цифрам, а не через float', () => {
    expect(compareDecimal('10', '9.999')).toBe(1);
    expect(compareDecimal('1.50', '1.5')).toBe(0);
    expect(compareDecimal('0.1', '0.10000000000000001')).toBe(-1);
    expect(compareDecimal('-2', '-10')).toBe(1);
  });
});
