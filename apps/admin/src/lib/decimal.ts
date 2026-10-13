/**
 * Десятичные значения — только строками.
 *
 * Backend отдаёт NUMERIC строкой («3500.50») и принимает строку.
 * Через `Number` значения здесь не проходят ни при показе, ни при вводе:
 * 0.1 + 0.2 в админке, где правят цены, недопустимо даже как побочный
 * эффект форматирования. Все операции — над цифрами строки.
 */

const DECIMAL_RE = /^(-?)(\d+)(?:\.(\d+))?$/;
const NBSP = ' ';

export type DecimalParts = { sign: string; integer: string; fraction: string };

export function parseDecimal(value: string): DecimalParts | null {
  const match = DECIMAL_RE.exec(value.trim());
  if (!match) return null;
  const integer = (match[2] ?? '0').replace(/^0+(?=\d)/, '');
  return { sign: match[1] ?? '', integer, fraction: match[3] ?? '' };
}

function groupThousands(integer: string): string {
  return integer.replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
}

type FormatOptions = {
  /** Сколько знаков дробной части показывать всегда (дополняется нулями). */
  minFraction?: number;
  /** Убирать хвостовые нули дробной части сверх `minFraction`. */
  trimZeros?: boolean;
};

/** «3500.50» → «3 500,50». Нечисловая строка возвращается как есть. */
export function formatDecimal(value: string, options: FormatOptions = {}): string {
  const parts = parseDecimal(value);
  if (!parts) return value;
  const { minFraction = 0, trimZeros = true } = options;
  let fraction = parts.fraction;
  if (trimZeros) fraction = fraction.replace(/0+$/, '');
  if (fraction.length < minFraction) fraction = fraction.padEnd(minFraction, '0');
  const isZero = /^0*$/.test(parts.integer + fraction);
  const sign = parts.sign && !isZero ? '−' : '';
  return `${sign}${groupThousands(parts.integer)}${fraction ? `,${fraction}` : ''}`;
}

/**
 * Деньги: копейки показываются, только если они есть.
 * «3500.00» → «3 500», «3500.5» → «3 500,50».
 */
export function formatMoney(value: string | null | undefined, currency?: string): string {
  if (value === null || value === undefined) return '—';
  const parts = parseDecimal(value);
  if (!parts) return value;
  const hasCents = /[1-9]/.test(parts.fraction);
  const amount = formatDecimal(value, { minFraction: hasCents ? 2 : 0, trimZeros: !hasCents });
  return currency ? `${amount}${NBSP}${currencySymbol(currency)}` : amount;
}

/** Количество: «5.000» → «5», «2.500» → «2,5». */
export function formatQuantity(value: string | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return formatDecimal(value, { trimZeros: true });
}

const CURRENCY_SYMBOLS: Record<string, string> = { KZT: '₸', RUB: '₽', USD: '$', EUR: '€' };

export function currencySymbol(code: string): string {
  return CURRENCY_SYMBOLS[code] ?? code;
}

export type DecimalInputResult = { ok: true; value: string } | { ok: false; error: string };

/**
 * Ввод из поля формы → строка для API.
 *
 * Принимает запятую и пробелы-разделители («3 500,5»), проверяет
 * число знаков — те же пределы, что у колонок NUMERIC(14,2)/(14,3)
 * и Pydantic-схем. Лишние знаки отвергаются, а не округляются молча.
 */
export function normalizeDecimalInput(
  raw: string,
  {
    maxFraction,
    maxDigits = 14,
    allowZero = true,
    allowNegative = false,
  }: { maxFraction: number; maxDigits?: number; allowZero?: boolean; allowNegative?: boolean },
): DecimalInputResult {
  const compact = raw.replace(/[\s  ]/g, '').replace(',', '.');
  if (!compact) return { ok: false, error: 'Введите число' };
  const parts = parseDecimal(compact);
  if (!parts) return { ok: false, error: 'Введите число' };
  if (parts.sign && !allowNegative) return { ok: false, error: 'Введите неотрицательное число' };
  const fraction = parts.fraction.replace(/0+$/, '');
  if (fraction.length > maxFraction) {
    return {
      ok: false,
      error:
        maxFraction === 0 ? 'Только целое число' : `Не больше ${maxFraction} знаков после запятой`,
    };
  }
  if (parts.integer.length + maxFraction > maxDigits) {
    return { ok: false, error: 'Слишком большое число' };
  }
  if (!allowZero && /^0*$/.test(parts.integer + fraction)) {
    return { ok: false, error: 'Значение должно быть больше нуля' };
  }
  const isZero = /^0*$/.test(parts.integer + fraction);
  const sign = parts.sign && !isZero ? '-' : '';
  return { ok: true, value: `${sign}${fraction ? `${parts.integer}.${fraction}` : parts.integer}` };
}

/** Сравнение двух десятичных строк без перевода в float: −1, 0, 1. */
export function compareDecimal(a: string, b: string): number {
  const left = parseDecimal(a);
  const right = parseDecimal(b);
  if (!left || !right) throw new Error(`Некорректное число: ${left ? b : a}`);
  const sign = (parts: DecimalParts) =>
    parts.sign && /[1-9]/.test(parts.integer + parts.fraction) ? -1 : 1;
  const leftSign = sign(left);
  const rightSign = sign(right);
  if (leftSign !== rightSign) return leftSign < rightSign ? -1 : 1;
  const width = Math.max(left.fraction.length, right.fraction.length);
  const leftDigits = left.integer + left.fraction.padEnd(width, '0');
  const rightDigits = right.integer + right.fraction.padEnd(width, '0');
  const leftNorm = leftDigits.replace(/^0+(?=\d)/, '');
  const rightNorm = rightDigits.replace(/^0+(?=\d)/, '');
  let result = 0;
  if (leftNorm.length !== rightNorm.length) result = leftNorm.length < rightNorm.length ? -1 : 1;
  else if (leftNorm !== rightNorm) result = leftNorm < rightNorm ? -1 : 1;
  return result * leftSign;
}
