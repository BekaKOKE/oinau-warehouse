/**
 * Дерево категорий и форма категории.
 *
 * Правила дерева (циклы, удаление с детьми и товарами, конфликт slug при
 * восстановлении) проверяет backend. Здесь — только то, что помогает не
 * отправлять заведомо отклонённый запрос: например, не предлагать в родители
 * саму категорию и её потомков.
 */

import { ApiError } from '@/lib/api/client';
import type {
  CategoryAttribute,
  CategoryAttributeItem,
  CategoryCreate,
  CategoryRead,
  CategoryTranslation,
  CategoryTreeNode,
  CategoryUpdate,
} from '@/lib/api/types';
import { extractFieldErrors } from '@/lib/errors';
import { slugError } from '@/lib/products';

export const DEFAULT_LOCALE = 'ru';

// ---------------------------------------------------------------- дерево

export type TreeIndex = {
  byId: Map<number, CategoryTreeNode>;
  parentOf: Map<number, number | null>;
};

export function indexTree(nodes: readonly CategoryTreeNode[]): TreeIndex {
  const byId = new Map<number, CategoryTreeNode>();
  const parentOf = new Map<number, number | null>();
  const walk = (list: readonly CategoryTreeNode[], parent: number | null) => {
    for (const node of list) {
      byId.set(node.id, node);
      parentOf.set(node.id, parent);
      walk(node.children ?? [], node.id);
    }
  };
  walk(nodes, null);
  return { byId, parentOf };
}

/** Id категории и всех её потомков. */
export function subtreeIds(node: CategoryTreeNode): Set<number> {
  const ids = new Set<number>([node.id]);
  for (const child of node.children ?? []) for (const id of subtreeIds(child)) ids.add(id);
  return ids;
}

/** Путь от корня: «Комплектующие / Канаты». */
export function pathOf(index: TreeIndex, id: number): string {
  const names: string[] = [];
  let current: number | null | undefined = id;
  while (current !== null && current !== undefined) {
    const node = index.byId.get(current);
    if (!node) break;
    names.unshift(node.name);
    current = index.parentOf.get(current);
  }
  return names.join(' / ');
}

export function liveChildren(node: CategoryTreeNode): CategoryTreeNode[] {
  return (node.children ?? []).filter((child) => !child.deleted_at);
}

/**
 * Фильтр дерева по названию или slug. Совпавшие узлы остаются вместе
 * с предками (иначе не видно, где они в дереве) и со всем поддеревом.
 */
export function filterTree(nodes: readonly CategoryTreeNode[], query: string): CategoryTreeNode[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [...nodes];
  const result: CategoryTreeNode[] = [];
  for (const node of nodes) {
    const matches = node.name.toLowerCase().includes(needle) || node.slug.includes(needle);
    if (matches) {
      result.push(node);
      continue;
    }
    const children = filterTree(node.children ?? [], needle);
    if (children.length > 0) result.push({ ...node, children });
  }
  return result;
}

/** Все id узлов, у которых есть дети, — для «Развернуть всё». */
export function expandableIds(nodes: readonly CategoryTreeNode[]): number[] {
  const ids: number[] = [];
  const walk = (list: readonly CategoryTreeNode[]) => {
    for (const node of list) {
      if ((node.children ?? []).length > 0) ids.push(node.id);
      walk(node.children ?? []);
    }
  };
  walk(nodes);
  return ids;
}

/**
 * Варианты родителя: живые категории, кроме самой категории и её потомков —
 * перенос в собственную ветку backend всё равно отклонит (category_cycle).
 */
export function parentOptions(
  nodes: readonly CategoryTreeNode[],
  exclude: Set<number>,
): { value: string; label: string }[] {
  const result: { value: string; label: string }[] = [];
  const walk = (list: readonly CategoryTreeNode[], depth: number) => {
    for (const node of list) {
      if (node.deleted_at || exclude.has(node.id)) continue;
      result.push({
        value: String(node.id),
        label: `${'  '.repeat(depth)}${node.name}${node.is_active ? '' : ' (скрыта)'}`,
      });
      walk(node.children ?? [], depth + 1);
    }
  };
  walk(nodes, 0);
  return result;
}

// ----------------------------------------------------------------- форма

export type CategoryForm = {
  name: string;
  slug: string;
  parentId: string;
  sortOrder: string;
  isActive: boolean;
  externalId: string;
  description: string;
  seoTitle: string;
  seoDescription: string;
  /** UUID файла медиатеки; пусто — обложки нет. */
  imageUuid: string;
  /** Ссылка на миниатюру для показа. В payload не уходит. */
  imageUrl: string;
};

export type CategoryFormField = keyof CategoryForm;
export type CategoryFormErrors = Partial<Record<CategoryFormField | '_form', string>>;

export function emptyCategoryForm(parentId: number | null = null): CategoryForm {
  return {
    name: '',
    slug: '',
    parentId: parentId ? String(parentId) : '',
    sortOrder: '0',
    isActive: true,
    externalId: '',
    description: '',
    seoTitle: '',
    seoDescription: '',
    imageUuid: '',
    imageUrl: '',
  };
}

export function formFromCategory(category: CategoryRead): CategoryForm {
  const ru = category.translations?.[DEFAULT_LOCALE];
  return {
    name: ru?.name ?? category.name,
    slug: category.slug,
    parentId: category.parent_id ? String(category.parent_id) : '',
    sortOrder: String(category.sort_order),
    isActive: category.is_active,
    externalId: category.external_id ?? '',
    description: ru?.description ?? '',
    seoTitle: ru?.seo_title ?? '',
    seoDescription: ru?.seo_description ?? '',
    imageUuid: category.image?.uuid ?? '',
    imageUrl: category.image?.url ?? '',
  };
}

export function isCategoryFormDirty(form: CategoryForm, initial: CategoryForm): boolean {
  return (Object.keys(initial) as CategoryFormField[]).some(
    // imageUrl — только для показа: он меняется вслед за imageUuid
    // и сам по себе несохранённых изменений не создаёт.
    (key) => key !== 'imageUrl' && form[key] !== initial[key],
  );
}

export function validateCategoryForm(form: CategoryForm): CategoryFormErrors {
  const errors: CategoryFormErrors = {};
  if (!form.name.trim()) errors.name = 'Укажите название';
  else if (form.name.trim().length > 500) errors.name = 'Не длиннее 500 символов';
  const slug = slugError(form.slug.trim());
  if (slug) errors.slug = slug;
  if (!/^-?\d+$/.test(form.sortOrder.trim())) errors.sortOrder = 'Целое число';
  if (form.seoTitle.trim().length > 500) errors.seoTitle = 'Не длиннее 500 символов';
  return errors;
}

function nullable(value: string): string | null {
  return value.trim() ? value.trim() : null;
}

/** Перевод целиком: backend перезаписывает все поля переданной локали. */
function translation(form: CategoryForm): CategoryTranslation {
  return {
    name: form.name.trim(),
    description: nullable(form.description),
    seo_title: nullable(form.seoTitle),
    seo_description: nullable(form.seoDescription),
  };
}

export function buildCategoryCreate(form: CategoryForm): CategoryCreate {
  return {
    slug: form.slug.trim(),
    parent_id: form.parentId ? Number(form.parentId) : null,
    sort_order: Number.parseInt(form.sortOrder, 10),
    is_active: form.isActive,
    external_id: nullable(form.externalId),
    image: form.imageUuid || null,
    translations: { [DEFAULT_LOCALE]: translation(form) },
  };
}

/** Только изменённые поля. parent_id: null — перенос в корень. */
export function buildCategoryUpdate(form: CategoryForm, initial: CategoryForm): CategoryUpdate {
  const payload: CategoryUpdate = {};
  if (form.slug.trim() !== initial.slug) payload.slug = form.slug.trim();
  if (form.parentId !== initial.parentId)
    payload.parent_id = form.parentId ? Number(form.parentId) : null;
  if (form.sortOrder.trim() !== initial.sortOrder)
    payload.sort_order = Number.parseInt(form.sortOrder, 10);
  if (form.isActive !== initial.isActive) payload.is_active = form.isActive;
  if (form.externalId.trim() !== initial.externalId)
    payload.external_id = nullable(form.externalId);
  // null снимает обложку; отсутствие ключа её не трогает.
  if (form.imageUuid !== initial.imageUuid) payload.image = form.imageUuid || null;
  if (
    form.name.trim() !== initial.name ||
    form.description.trim() !== initial.description.trim() ||
    form.seoTitle.trim() !== initial.seoTitle.trim() ||
    form.seoDescription.trim() !== initial.seoDescription.trim()
  ) {
    payload.translations = { [DEFAULT_LOCALE]: translation(form) };
  }
  return payload;
}

const API_FIELD: Record<string, CategoryFormField> = {
  slug: 'slug',
  parent_id: 'parentId',
  sort_order: 'sortOrder',
  is_active: 'isActive',
  external_id: 'externalId',
  [`translations.${DEFAULT_LOCALE}.name`]: 'name',
  [`translations.${DEFAULT_LOCALE}.description`]: 'description',
  [`translations.${DEFAULT_LOCALE}.seo_title`]: 'seoTitle',
  [`translations.${DEFAULT_LOCALE}.seo_description`]: 'seoDescription',
};

/** Конфликты backend, относящиеся к полю формы. */
const CONFLICT_FIELD: Record<string, CategoryFormField> = {
  slug_exists: 'slug',
  category_cycle: 'parentId',
  parent_deleted: 'parentId',
  external_id_exists: 'externalId',
};

export function categoryErrorsFromApi(error: unknown): CategoryFormErrors {
  if (error instanceof ApiError && error.status === 404) {
    // Родитель исчез между загрузкой формы и сохранением.
    return error.message.includes('Родитель')
      ? { parentId: error.message }
      : { _form: error.message };
  }
  if (error instanceof ApiError && error.status === 409) {
    const field = CONFLICT_FIELD[error.code];
    return field ? { [field]: error.message } : { _form: error.message };
  }
  const result: CategoryFormErrors = {};
  for (const [path, message] of Object.entries(extractFieldErrors(error))) {
    const field = API_FIELD[path];
    if (field) result[field] = message;
    else result._form = result._form ?? message;
  }
  return result;
}

// ------------------------------------------- характеристики категории

export type AssignedAttribute = CategoryAttributeItem & {
  code: string;
  name: string;
  value_type: CategoryAttribute['value_type'];
  unit: string | null;
};

export function assignedFromApi(items: readonly CategoryAttribute[]): AssignedAttribute[] {
  return [...items]
    .sort((a, b) => a.sort_order - b.sort_order || a.attribute_id - b.attribute_id)
    .map((item) => ({
      attribute_id: item.attribute_id,
      sort_order: item.sort_order,
      is_required: item.is_required,
      code: item.code,
      name: item.name,
      value_type: item.value_type,
      unit: item.unit,
    }));
}

/** Тело PUT: порядок в списке становится sort_order. */
export function assignedToItems(items: readonly AssignedAttribute[]): CategoryAttributeItem[] {
  return items.map((item, index) => ({
    attribute_id: item.attribute_id,
    sort_order: index,
    is_required: Boolean(item.is_required),
  }));
}

export function assignedSignature(items: readonly AssignedAttribute[]): string {
  return assignedToItems(items)
    .map((item) => `${item.attribute_id}:${item.is_required ? 1 : 0}`)
    .join(',');
}
