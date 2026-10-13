/**
 * Основная форма товара: состояние, сборка тела запроса и разбор ошибок.
 *
 * Форма хранит строки. В API уходит только то, что изменилось (PATCH
 * частичный), а перевод — целиком, со всеми полями: backend перезаписывает
 * русскую версию переданными полями, и без SEO-полей они бы стёрлись.
 */

import { ApiError } from '@/lib/api/client';
import type {
  ProductCreate,
  ProductRead,
  ProductStatus,
  ProductTranslation,
  ProductUpdate,
} from '@/lib/api/types';
import { normalizeDecimalInput } from '@/lib/decimal';
import { extractFieldErrors } from '@/lib/errors';
import { skuError, slugError } from '@/lib/products';

export const DEFAULT_LOCALE = 'ru';

export type MainForm = {
  name: string;
  shortDescription: string;
  description: string;
  sku: string;
  slug: string;
  status: ProductStatus;
  unit: string;
  minOrderQty: string;
  brand: string;
  externalId: string;
  isActive: boolean;
  isFeatured: boolean;
};

export type MainFormField = keyof MainForm;
export type MainFormErrors = Partial<Record<MainFormField | '_form', string>>;

export const EMPTY_MAIN_FORM: MainForm = {
  name: '',
  shortDescription: '',
  description: '',
  sku: '',
  slug: '',
  status: 'DRAFT',
  unit: 'pcs',
  minOrderQty: '1',
  brand: '',
  externalId: '',
  isActive: true,
  isFeatured: false,
};

function trimQty(value: string): string {
  return value.includes('.') ? value.replace(/\.?0+$/, '') : value;
}

export function formFromProduct(product: ProductRead): MainForm {
  const ru = product.translations?.[DEFAULT_LOCALE];
  return {
    name: ru?.name ?? product.name,
    shortDescription: ru?.short_description ?? '',
    description: ru?.description ?? '',
    sku: product.sku,
    slug: product.slug,
    status: product.status,
    unit: product.unit,
    minOrderQty: trimQty(product.min_order_qty),
    brand: product.brand ?? '',
    externalId: product.external_id ?? '',
    isActive: product.is_active,
    isFeatured: product.is_featured,
  };
}

export function validateMainForm(form: MainForm): MainFormErrors {
  const errors: MainFormErrors = {};
  if (!form.name.trim()) errors.name = 'Укажите название';
  else if (form.name.trim().length > 500) errors.name = 'Не длиннее 500 символов';
  const sku = skuError(form.sku.trim());
  if (sku) errors.sku = sku;
  const slug = slugError(form.slug.trim());
  if (slug) errors.slug = slug;
  if (!form.unit.trim()) errors.unit = 'Укажите единицу';
  const qty = normalizeDecimalInput(form.minOrderQty, { maxFraction: 3, allowZero: false });
  if (!qty.ok) errors.minOrderQty = qty.error;
  return errors;
}

function nullable(value: string): string | null {
  return value.trim() ? value.trim() : null;
}

function translation(form: MainForm, existing?: ProductTranslation): ProductTranslation {
  return {
    name: form.name.trim(),
    short_description: nullable(form.shortDescription),
    description: nullable(form.description),
    // Поля, которых нет в форме, передаются как были — иначе стёрлись бы.
    seo_title: existing?.seo_title ?? null,
    seo_description: existing?.seo_description ?? null,
  };
}

function minOrderQty(form: MainForm): string {
  const qty = normalizeDecimalInput(form.minOrderQty, { maxFraction: 3, allowZero: false });
  return qty.ok ? qty.value : form.minOrderQty;
}

export function buildCreatePayload(
  form: MainForm,
  extra: Pick<ProductCreate, 'categories' | 'attributes'>,
): ProductCreate {
  return {
    sku: form.sku.trim(),
    slug: form.slug.trim(),
    status: form.status,
    is_active: form.isActive,
    is_featured: form.isFeatured,
    unit: form.unit.trim(),
    min_order_qty: minOrderQty(form),
    brand: nullable(form.brand),
    external_id: nullable(form.externalId),
    translations: { [DEFAULT_LOCALE]: translation(form) },
    ...extra,
  };
}

/** Только изменившиеся поля. Пустой объект — сохранять нечего. */
export function buildUpdatePayload(form: MainForm, product: ProductRead): ProductUpdate {
  const initial = formFromProduct(product);
  const payload: ProductUpdate = {};
  if (form.sku.trim() !== initial.sku) payload.sku = form.sku.trim();
  if (form.slug.trim() !== initial.slug) payload.slug = form.slug.trim();
  if (form.status !== initial.status) payload.status = form.status;
  if (form.isActive !== initial.isActive) payload.is_active = form.isActive;
  if (form.isFeatured !== initial.isFeatured) payload.is_featured = form.isFeatured;
  if (form.unit.trim() !== initial.unit) payload.unit = form.unit.trim();
  if (minOrderQty(form) !== initial.minOrderQty) payload.min_order_qty = minOrderQty(form);
  if (form.brand.trim() !== initial.brand) payload.brand = nullable(form.brand);
  if (form.externalId.trim() !== initial.externalId)
    payload.external_id = nullable(form.externalId);
  if (
    form.name.trim() !== initial.name ||
    form.shortDescription.trim() !== initial.shortDescription.trim() ||
    form.description.trim() !== initial.description.trim()
  ) {
    payload.translations = {
      [DEFAULT_LOCALE]: translation(form, product.translations?.[DEFAULT_LOCALE]),
    };
  }
  return payload;
}

export function isFormDirty(form: MainForm, initial: MainForm): boolean {
  return (Object.keys(initial) as MainFormField[]).some((key) => form[key] !== initial[key]);
}

const API_FIELD: Record<string, MainFormField> = {
  sku: 'sku',
  slug: 'slug',
  status: 'status',
  unit: 'unit',
  min_order_qty: 'minOrderQty',
  brand: 'brand',
  external_id: 'externalId',
  is_active: 'isActive',
  is_featured: 'isFeatured',
  [`translations.${DEFAULT_LOCALE}.name`]: 'name',
  [`translations.${DEFAULT_LOCALE}.short_description`]: 'shortDescription',
  [`translations.${DEFAULT_LOCALE}.description`]: 'description',
};

/** Коды конфликтов backend (409), которые относятся к конкретному полю. */
const CONFLICT_FIELD: Record<string, MainFormField> = {
  sku_exists: 'sku',
  product_slug_exists: 'slug',
  external_id_exists: 'externalId',
};

/** Ошибки backend → поля формы; всё непривязываемое — в `_form`. */
export function mainFormErrorsFromApi(error: unknown): MainFormErrors {
  if (error instanceof ApiError && error.status === 409) {
    const field = CONFLICT_FIELD[error.code];
    return field ? { [field]: error.message } : { _form: error.message };
  }
  const result: MainFormErrors = {};
  for (const [path, message] of Object.entries(extractFieldErrors(error))) {
    const field = API_FIELD[path];
    if (field) result[field] = message;
    else result._form = result._form ?? message;
  }
  return result;
}
