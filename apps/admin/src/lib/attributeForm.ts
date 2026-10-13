/**
 * Форма характеристики и вариантов значений.
 *
 * Код и тип значения задаются только при создании: в AttributeUpdate их
 * нет, смена типа осиротила бы значения товаров. Интерфейс показывает их
 * после создания только для чтения.
 */

import { ApiError } from '@/lib/api/client';
import type {
  AttributeCreate,
  AttributeOption,
  AttributeRead,
  AttributeUpdate,
  AttributeValueType,
} from '@/lib/api/types';
import { extractFieldErrors } from '@/lib/errors';
import { slugError } from '@/lib/products';

export const DEFAULT_LOCALE = 'ru';

/** Совпадает с CodeField в schemas_admin.py. */
const CODE_RE = /^[a-z0-9_]+$/;

export type AttributeForm = {
  name: string;
  code: string;
  valueType: AttributeValueType;
  unit: string;
  sortOrder: string;
  isActive: boolean;
  isFilterable: boolean;
  isVisible: boolean;
};

export type AttributeFormField = keyof AttributeForm;
export type AttributeFormErrors = Partial<Record<AttributeFormField | '_form', string>>;

export const EMPTY_ATTRIBUTE_FORM: AttributeForm = {
  name: '',
  code: '',
  valueType: 'STRING',
  unit: '',
  sortOrder: '0',
  isActive: true,
  isFilterable: true,
  isVisible: true,
};

export function formFromAttribute(attribute: AttributeRead): AttributeForm {
  return {
    name: attribute.names?.[DEFAULT_LOCALE] ?? attribute.name,
    code: attribute.code,
    valueType: attribute.value_type,
    unit: attribute.unit ?? '',
    sortOrder: String(attribute.sort_order),
    isActive: attribute.is_active,
    isFilterable: attribute.is_filterable,
    isVisible: attribute.is_visible,
  };
}

export function validateAttributeForm(form: AttributeForm, creating: boolean): AttributeFormErrors {
  const errors: AttributeFormErrors = {};
  if (!form.name.trim()) errors.name = 'Укажите название';
  if (creating) {
    if (!form.code.trim()) errors.code = 'Укажите код';
    else if (form.code.length > 64) errors.code = 'Не длиннее 64 символов';
    else if (!CODE_RE.test(form.code.trim())) errors.code = 'Строчная латиница, цифры и _';
  }
  if (form.unit.trim().length > 16) errors.unit = 'Не длиннее 16 символов';
  if (!/^-?\d+$/.test(form.sortOrder.trim())) errors.sortOrder = 'Целое число';
  return errors;
}

export function buildAttributeCreate(
  form: AttributeForm,
  options: readonly OptionDraft[] = [],
): AttributeCreate {
  return {
    code: form.code.trim(),
    value_type: form.valueType,
    unit: form.unit.trim() || null,
    is_filterable: form.isFilterable,
    is_visible: form.isVisible,
    is_active: form.isActive,
    sort_order: Number.parseInt(form.sortOrder, 10),
    names: { [DEFAULT_LOCALE]: form.name.trim() },
    options:
      form.valueType === 'OPTION'
        ? options.map((option, index) => ({
            slug: option.slug.trim(),
            sort_order: index,
            values: { [DEFAULT_LOCALE]: option.value.trim() },
          }))
        : [],
  };
}

export function buildAttributeUpdate(form: AttributeForm, initial: AttributeForm): AttributeUpdate {
  const payload: AttributeUpdate = {};
  if (form.name.trim() !== initial.name) payload.names = { [DEFAULT_LOCALE]: form.name.trim() };
  if (form.unit.trim() !== initial.unit) payload.unit = form.unit.trim() || null;
  if (form.sortOrder.trim() !== initial.sortOrder)
    payload.sort_order = Number.parseInt(form.sortOrder, 10);
  if (form.isActive !== initial.isActive) payload.is_active = form.isActive;
  if (form.isFilterable !== initial.isFilterable) payload.is_filterable = form.isFilterable;
  if (form.isVisible !== initial.isVisible) payload.is_visible = form.isVisible;
  return payload;
}

const API_FIELD: Record<string, AttributeFormField> = {
  code: 'code',
  value_type: 'valueType',
  unit: 'unit',
  sort_order: 'sortOrder',
  [`names.${DEFAULT_LOCALE}`]: 'name',
  names: 'name',
};

export function attributeErrorsFromApi(error: unknown): AttributeFormErrors {
  if (error instanceof ApiError && error.status === 409) {
    return error.code === 'attribute_code_exists'
      ? { code: error.message }
      : { _form: error.message };
  }
  const result: AttributeFormErrors = {};
  for (const [path, message] of Object.entries(extractFieldErrors(error))) {
    const field = API_FIELD[path];
    if (field) result[field] = message;
    else result._form = result._form ?? message;
  }
  return result;
}

// -------------------------------------------------------------- варианты

export type OptionDraft = { key: string; value: string; slug: string };

let draftSeq = 0;
export function newOptionDraft(): OptionDraft {
  draftSeq += 1;
  return { key: `option-${draftSeq}`, value: '', slug: '' };
}

export function optionValue(option: AttributeOption): string {
  return option.values?.[DEFAULT_LOCALE] ?? Object.values(option.values ?? {})[0] ?? option.slug;
}

export function optionDraftError(draft: Pick<OptionDraft, 'value' | 'slug'>): {
  value?: string;
  slug?: string;
} {
  const errors: { value?: string; slug?: string } = {};
  if (!draft.value.trim()) errors.value = 'Укажите значение';
  const slug = slugError(draft.slug.trim());
  if (slug) errors.slug = slug;
  return errors;
}

export const VALUE_TYPE_META: Record<AttributeValueType, { label: string; hint: string }> = {
  STRING: { label: 'Текст', hint: 'Произвольная строка до 255 символов' },
  NUMBER: { label: 'Число', hint: 'Десятичное число, до 3 знаков после запятой' },
  BOOLEAN: { label: 'Да / нет', hint: 'Признак: да или нет' },
  OPTION: { label: 'Список', hint: 'Значения из списка вариантов; можно несколько' },
};
