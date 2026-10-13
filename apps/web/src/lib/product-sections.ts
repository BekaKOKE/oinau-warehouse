/**
 * Разбор характеристик товара по блокам страницы.
 *
 * Отдельных полей «цвет» и «упаковка» в модели нет: это характеристики
 * (фильтры) или описательные характеристики товара. Витрина лишь
 * раскладывает их по блокам по названию — данные не придумываются.
 */

import type { ProductDetail } from '@oinau/api-types';

export type SpecRow = { key: string; name: string; value: string };

const COLOR_CODES = new Set(['color', 'colour', 'cvet', 'tsvet']);
const COLOR_NAME = /^цвет/i;
const PACKAGING_NAME = /упаков|в коробке|кратность|вес брутто|габарит/i;

export type ProductSections = {
  color: string | null;
  characteristics: SpecRow[];
  packaging: SpecRow[];
};

export function productSections(product: ProductDetail): ProductSections {
  const rows: Array<SpecRow & { code: string }> = [
    ...(product.characteristics ?? []).map((item) => ({
      key: `attr:${item.code}`,
      name: item.name,
      value: item.value,
      code: item.code,
    })),
    ...Object.entries(product.specs ?? {}).map(([name, value]) => ({
      key: `spec:${name}`,
      name,
      value: String(value),
      code: '',
    })),
  ];

  const colorRow = rows.find((row) => COLOR_CODES.has(row.code) || COLOR_NAME.test(row.name));
  const seen = new Set<string>();
  const characteristics: SpecRow[] = [];
  const packaging: SpecRow[] = [];
  for (const { key, name, value } of rows) {
    // Одно и то же свойство бывает и фильтром, и описанием — показываем раз.
    if (seen.has(name.toLowerCase())) continue;
    seen.add(name.toLowerCase());
    (PACKAGING_NAME.test(name) ? packaging : characteristics).push({ key, name, value });
  }

  return { color: colorRow?.value ?? null, characteristics, packaging };
}
