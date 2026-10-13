/**
 * Значения характеристик товара.
 *
 * Типы — только из backend (AttributeValueType): STRING, NUMBER, BOOLEAN,
 * OPTION. Для каждого типа заполняется ровно одно поле значения — то же
 * правило, что CHECK `num_nonnulls(...) = 1` в базе. OPTION допускает
 * несколько вариантов (товар в трёх цветах).
 */

import type {
  AttributeOption,
  AttributeValueType,
  CategoryAttribute,
  ProductAttributeItem,
  ProductAttributeRead,
} from '@/lib/api/types';
import { normalizeDecimalInput } from '@/lib/decimal';

export type AttributeDef = {
  id: number;
  code: string;
  name: string;
  valueType: AttributeValueType;
  unit: string | null;
  /** Отмечена обязательной хотя бы в одной категории товара (подсказка, не блокировка). */
  required: boolean;
  /** Характеристика назначена одной из категорий товара. */
  fromCategory: boolean;
  options: AttributeOption[];
  sortOrder: number;
};

export type AttributeValue =
  | { type: 'STRING'; text: string }
  | { type: 'NUMBER'; text: string }
  | { type: 'BOOLEAN'; value: '' | 'true' | 'false' }
  | { type: 'OPTION'; optionIds: number[] };

export type AttributeValues = Record<number, AttributeValue>;

export const VALUE_TYPE_LABELS: Record<AttributeValueType, string> = {
  STRING: 'Текст',
  NUMBER: 'Число',
  BOOLEAN: 'Да / нет',
  OPTION: 'Вариант из списка',
};

export function emptyValue(type: AttributeValueType): AttributeValue {
  switch (type) {
    case 'STRING':
      return { type, text: '' };
    case 'NUMBER':
      return { type, text: '' };
    case 'BOOLEAN':
      return { type, value: '' };
    case 'OPTION':
      return { type, optionIds: [] };
  }
}

/**
 * Список характеристик для формы: назначенные категориям товара плюс
 * уже заполненные у товара (даже если категорию сменили — данные не
 * пропадают молча, их видно и можно очистить).
 */
export function buildDefs(
  categoryAttributes: readonly CategoryAttribute[][],
  existing: readonly ProductAttributeRead[],
  options: Record<number, AttributeOption[]>,
): AttributeDef[] {
  const defs = new Map<number, AttributeDef>();
  for (const list of categoryAttributes) {
    for (const item of list) {
      const current = defs.get(item.attribute_id);
      defs.set(item.attribute_id, {
        id: item.attribute_id,
        code: item.code,
        name: item.name,
        valueType: item.value_type,
        unit: item.unit,
        required: Boolean(current?.required || item.is_required),
        fromCategory: true,
        options: options[item.attribute_id] ?? [],
        sortOrder: Math.min(current?.sortOrder ?? item.sort_order, item.sort_order),
      });
    }
  }
  for (const item of existing) {
    if (defs.has(item.attribute_id)) continue;
    defs.set(item.attribute_id, {
      id: item.attribute_id,
      code: item.code,
      name: item.name,
      valueType: item.value_type,
      unit: item.unit,
      required: false,
      fromCategory: false,
      options: options[item.attribute_id] ?? [],
      sortOrder: Number.MAX_SAFE_INTEGER,
    });
  }
  return [...defs.values()].sort(
    (a, b) =>
      Number(b.fromCategory) - Number(a.fromCategory) ||
      a.sortOrder - b.sortOrder ||
      a.name.localeCompare(b.name, 'ru'),
  );
}

function trimQty(value: string): string {
  return value.includes('.') ? value.replace(/\.?0+$/, '') : value;
}

/** Значения товара из API → состояние формы. */
export function valuesFromProduct(existing: readonly ProductAttributeRead[]): AttributeValues {
  const values: AttributeValues = {};
  for (const item of existing) {
    switch (item.value_type) {
      case 'STRING':
        values[item.attribute_id] = { type: 'STRING', text: item.value_string ?? '' };
        break;
      case 'NUMBER':
        values[item.attribute_id] = {
          type: 'NUMBER',
          text: item.value_numeric ? trimQty(item.value_numeric) : '',
        };
        break;
      case 'BOOLEAN':
        values[item.attribute_id] = {
          type: 'BOOLEAN',
          value:
            item.value_bool === null || item.value_bool === undefined
              ? ''
              : item.value_bool
                ? 'true'
                : 'false',
        };
        break;
      case 'OPTION': {
        const current = values[item.attribute_id];
        const ids = current?.type === 'OPTION' ? current.optionIds : [];
        values[item.attribute_id] = {
          type: 'OPTION',
          optionIds: item.option_id ? [...ids, item.option_id] : ids,
        };
        break;
      }
    }
  }
  return values;
}

export type AttributeBuild =
  { ok: true; items: ProductAttributeItem[] } | { ok: false; errors: Record<number, string> };

/** Состояние формы → тело PUT /attributes. Пустые значения не отправляются. */
export function buildAttributeItems(
  defs: readonly AttributeDef[],
  values: AttributeValues,
): AttributeBuild {
  const items: ProductAttributeItem[] = [];
  const errors: Record<number, string> = {};
  for (const def of defs) {
    const value = values[def.id];
    if (!value) continue;
    switch (value.type) {
      case 'STRING': {
        const text = value.text.trim();
        if (!text) break;
        if (text.length > 255) errors[def.id] = 'Не длиннее 255 символов';
        else items.push({ attribute_id: def.id, value_string: text });
        break;
      }
      case 'NUMBER': {
        if (!value.text.trim()) break;
        const number = normalizeDecimalInput(value.text, { maxFraction: 3, allowNegative: true });
        if (!number.ok) errors[def.id] = number.error;
        else items.push({ attribute_id: def.id, value_numeric: number.value });
        break;
      }
      case 'BOOLEAN':
        if (value.value) items.push({ attribute_id: def.id, value_bool: value.value === 'true' });
        break;
      case 'OPTION':
        for (const optionId of value.optionIds)
          items.push({ attribute_id: def.id, option_id: optionId });
        break;
    }
  }
  return Object.keys(errors).length > 0 ? { ok: false, errors } : { ok: true, items };
}

/** Сравнение для защиты от потери несохранённых изменений. */
export function sameItems(
  a: readonly ProductAttributeItem[],
  b: readonly ProductAttributeItem[],
): boolean {
  const key = (item: ProductAttributeItem) =>
    `${item.attribute_id}|${item.value_string ?? ''}|${item.value_numeric ?? ''}|${item.value_bool ?? ''}|${item.option_id ?? ''}`;
  const left = a.map(key).sort();
  const right = b.map(key).sort();
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

/** Подпись варианта в текущей локали. */
export function optionLabel(option: AttributeOption): string {
  return option.values.ru ?? Object.values(option.values)[0] ?? option.slug;
}
