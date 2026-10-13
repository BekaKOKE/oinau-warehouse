/**
 * Эндпоинты Admin API, которыми пользуется интерфейс.
 *
 * Функции тонкие: путь, метод и типы из OpenAPI. Бизнес-правил здесь
 * нет — их проверяет backend, а экран показывает его ответ.
 */

import { rawRequest } from '@/lib/api/client';
import { adminDownload, adminRequest, adminUpload, AUTH_BASE } from '@/lib/auth/session';

import type {
  AttributeCreate,
  AttributeListQuery,
  AttributeOption,
  AttributeOptionCreate,
  AttributeOptionUpdate,
  AttributePage,
  AttributeRead,
  AttributeUpdate,
  CategoryAttributeItem,
  CategoryCreate,
  CategoryRead,
  CategoryUpdate,
  AuditLogPage,
  AvailabilityRead,
  CategoryAttribute,
  CategoryTreeNode,
  Color,
  ColorCreate,
  ColorUpdate,
  ContentSectionData,
  ContentSectionKey,
  ContentSectionRead,
  ContentSectionSummary,
  MediaDetail,
  MediaListQuery,
  MediaPage,
  MediaPurpose,
  MediaRead,
  MediaUploadCreated,
  PricingRead,
  PricingUpdate,
  ProductColors,
  ProductColorsUpdate,
  ProductAttributeItem,
  ProductCategoryItem,
  ProductCreate,
  ProductImageList,
  ProductRead,
  ProductStock,
  ProductUpdate,
  StockDisplayOverride,
  StockUpdate,
  AuditLogQuery,
  CatalogSummary,
  CategoryPage,
  CurrentUser,
  ImportCommitResult,
  ImportJobDetail,
  ImportJobPage,
  BundleJob,
  BundleUploadCreated,
  ImportListQuery,
  ImportPreview,
  IntegrationStatus,
  ProductListQuery,
  ProductPage,
  ProductStockPage,
  AdminUser,
  Region,
  RequestComment,
  RequestCommentCreate,
  RequestDetail,
  RequestListQuery,
  RequestPage,
  RequestStatusUpdate,
  RolePermissions,
  StockListQuery,
  UserCreate,
  UserListQuery,
  UserPage,
  UserUpdate,
  Warehouse,
  WarehouseCreate,
  WarehouseListQuery,
  WarehousePage,
  WarehouseUpdate,
} from './types';

const ADMIN = '/api/v1/admin';

type Signal = { signal?: AbortSignal };

export const authApi = {
  me: ({ signal }: Signal = {}) => adminRequest<CurrentUser>(`${AUTH_BASE}/me`, { signal }),
};

export const productsApi = {
  list: (query: ProductListQuery, { signal }: Signal = {}) =>
    adminRequest<ProductPage>(`${ADMIN}/products`, { query, signal }),
  get: (id: number, { signal }: Signal = {}) =>
    adminRequest<ProductRead>(`${ADMIN}/products/${id}`, { signal }),
  create: (body: ProductCreate) =>
    adminRequest<ProductRead>(`${ADMIN}/products`, { method: 'POST', body }),
  /** Частичное обновление: незаданные поля backend не трогает. */
  update: (id: number, body: ProductUpdate) =>
    adminRequest<ProductRead>(`${ADMIN}/products/${id}`, { method: 'PATCH', body }),
  remove: (id: number) => adminRequest<void>(`${ADMIN}/products/${id}`, { method: 'DELETE' }),
  restore: (id: number) =>
    adminRequest<ProductRead>(`${ADMIN}/products/${id}/restore`, { method: 'POST' }),
  /** Полная замена набора категорий. */
  setCategories: (id: number, items: ProductCategoryItem[]) =>
    adminRequest<ProductRead>(`${ADMIN}/products/${id}/categories`, {
      method: 'PUT',
      body: { items },
    }),
  /** Полная замена значений характеристик. */
  setAttributes: (id: number, items: ProductAttributeItem[]) =>
    adminRequest<ProductRead>(`${ADMIN}/products/${id}/attributes`, {
      method: 'PUT',
      body: { items },
    }),
};

export const pricingApi = {
  get: (productId: number, { signal }: Signal = {}) =>
    adminRequest<PricingRead>(`${ADMIN}/products/${productId}/pricing`, { signal }),
  /** Полная замена типа цены и ступеней одной транзакцией. */
  set: (productId: number, body: PricingUpdate) =>
    adminRequest<PricingRead>(`${ADMIN}/products/${productId}/pricing`, {
      method: 'PUT',
      body,
    }),
};

export const productStockApi = {
  get: (productId: number, { signal }: Signal = {}) =>
    adminRequest<ProductStock>(`${ADMIN}/products/${productId}/stock`, { signal }),
  /** Upsert по перечисленным складам; остальные склады не трогаются. */
  set: (productId: number, body: StockUpdate) =>
    adminRequest<ProductStock>(`${ADMIN}/products/${productId}/stock`, { method: 'PUT', body }),
  /** Меняет только показ на сайте, не остатки. null — снять переопределение. */
  setOverride: (productId: number, override: StockDisplayOverride | null) =>
    adminRequest<AvailabilityRead>(`${ADMIN}/products/${productId}/availability`, {
      method: 'PATCH',
      body: { stock_display_override: override },
    }),
};

/** Цвета товара: остаток и надбавка по каждому цвету. */
export const productColorsApi = {
  get: (productId: number, { signal }: Signal = {}) =>
    adminRequest<ProductColors>(`${ADMIN}/products/${productId}/colors`, { signal }),
  /** Полная замена набора цветов; порядок списка — порядок на сайте. */
  set: (productId: number, body: ProductColorsUpdate) =>
    adminRequest<ProductColors>(`${ADMIN}/products/${productId}/colors`, {
      method: 'PUT',
      body,
    }),
};

/** Справочник цветов. Используемый цвет не удаляется — отключается. */
export const colorsApi = {
  list: ({ signal }: Signal = {}) => adminRequest<Color[]>(`${ADMIN}/colors`, { signal }),
  create: (body: ColorCreate) => adminRequest<Color>(`${ADMIN}/colors`, { method: 'POST', body }),
  update: (id: number, body: ColorUpdate) =>
    adminRequest<Color>(`${ADMIN}/colors/${id}`, { method: 'PATCH', body }),
  remove: (id: number) => adminRequest<void>(`${ADMIN}/colors/${id}`, { method: 'DELETE' }),
};

export const mediaApi = {
  list: (query: MediaListQuery, { signal }: Signal = {}) =>
    adminRequest<MediaPage>(`${ADMIN}/media`, { query, signal }),
  /** Назначение задаёт только префикс ключа в бакете (products/ или content/). */
  uploadIntent: (
    file: { filename: string; content_type: string; size_bytes: number },
    purpose: MediaPurpose = 'PRODUCT',
  ) =>
    adminRequest<MediaUploadCreated>(`${ADMIN}/media/upload-intent`, {
      method: 'POST',
      body: { ...file, purpose },
    }),
  complete: (uuid: string) =>
    adminRequest<MediaRead>(`${ADMIN}/media/${uuid}/complete`, { method: 'POST' }),
  get: (uuid: string, { signal }: Signal = {}) =>
    adminRequest<MediaDetail>(`${ADMIN}/media/${uuid}`, { signal }),
};

export const productImagesApi = {
  list: (productId: number, { signal }: Signal = {}) =>
    adminRequest<ProductImageList>(`${ADMIN}/products/${productId}/images`, { signal }),
  /** PENDING/PROCESSING-файл привязать можно — витрина покажет его, когда он станет READY. */
  attach: (productId: number, mediaUuid: string) =>
    adminRequest<ProductImageList>(`${ADMIN}/products/${productId}/images`, {
      method: 'POST',
      body: { media_uuid: mediaUuid },
    }),
  /** Полный новый порядок — список id всех изображений товара. */
  reorder: (productId: number, imageIds: number[]) =>
    adminRequest<ProductImageList>(`${ADMIN}/products/${productId}/images/order`, {
      method: 'PUT',
      body: { image_ids: imageIds },
    }),
  setMain: (productId: number, imageId: number) =>
    adminRequest<ProductImageList>(`${ADMIN}/products/${productId}/images/main`, {
      method: 'PUT',
      body: { image_id: imageId },
    }),
  /** Отвязка: файл остаётся в медиатеке. */
  detach: (productId: number, imageId: number) =>
    adminRequest<void>(`${ADMIN}/products/${productId}/images/${imageId}`, { method: 'DELETE' }),
};

export const attributesApi = {
  list: (query: AttributeListQuery, { signal }: Signal = {}) =>
    adminRequest<AttributePage>(`${ADMIN}/attributes`, { query, signal }),
  /**
   * Все характеристики — для выбора в категории. Страница backend не больше
   * 60 записей, поэтому листаем до конца; характеристик десятки, а не тысячи.
   */
  listAll: async ({ signal }: Signal = {}): Promise<AttributeRead[]> => {
    const items: AttributeRead[] = [];
    for (let page = 1; page <= 50; page += 1) {
      const result = await adminRequest<AttributePage>(`${ADMIN}/attributes`, {
        query: { page, page_size: 60 },
        signal,
      });
      items.push(...result.items);
      if (page >= result.pages) break;
    }
    return items;
  },
  get: (id: number, { signal }: Signal = {}) =>
    adminRequest<AttributeRead>(`${ADMIN}/attributes/${id}`, { signal }),
  create: (body: AttributeCreate) =>
    adminRequest<AttributeRead>(`${ADMIN}/attributes`, { method: 'POST', body }),
  /** value_type и code не меняются — их нет в AttributeUpdate. */
  update: (id: number, body: AttributeUpdate) =>
    adminRequest<AttributeRead>(`${ADMIN}/attributes/${id}`, { method: 'PATCH', body }),
  remove: (id: number) => adminRequest<void>(`${ADMIN}/attributes/${id}`, { method: 'DELETE' }),
  createOption: (id: number, body: AttributeOptionCreate) =>
    adminRequest<AttributeOption>(`${ADMIN}/attributes/${id}/options`, { method: 'POST', body }),
  updateOption: (id: number, optionId: number, body: AttributeOptionUpdate) =>
    adminRequest<AttributeOption>(`${ADMIN}/attributes/${id}/options/${optionId}`, {
      method: 'PATCH',
      body,
    }),
  removeOption: (id: number, optionId: number) =>
    adminRequest<void>(`${ADMIN}/attributes/${id}/options/${optionId}`, { method: 'DELETE' }),
};

export const categoriesApi = {
  list: (
    query: { page?: number; page_size?: number; include_deleted?: boolean } = {},
    { signal }: Signal = {},
  ) => adminRequest<CategoryPage>(`${ADMIN}/categories`, { query, signal }),
  /** Всё дерево одним запросом; с includeDeleted — вместе с удалёнными. */
  tree: ({ signal, includeDeleted = false }: Signal & { includeDeleted?: boolean } = {}) =>
    adminRequest<CategoryTreeNode[]>(`${ADMIN}/categories/tree`, {
      query: { include_deleted: includeDeleted || undefined },
      signal,
    }),
  get: (id: number, { signal }: Signal = {}) =>
    adminRequest<CategoryRead>(`${ADMIN}/categories/${id}`, { signal }),
  create: (body: CategoryCreate) =>
    adminRequest<CategoryRead>(`${ADMIN}/categories`, { method: 'POST', body }),
  /** Частичное обновление; смена parent_id переносит всю ветку. */
  update: (id: number, body: CategoryUpdate) =>
    adminRequest<CategoryRead>(`${ADMIN}/categories/${id}`, { method: 'PATCH', body }),
  remove: (id: number) => adminRequest<void>(`${ADMIN}/categories/${id}`, { method: 'DELETE' }),
  restore: (id: number) =>
    adminRequest<CategoryRead>(`${ADMIN}/categories/${id}/restore`, { method: 'POST' }),
  attributes: (id: number, { signal }: Signal = {}) =>
    adminRequest<CategoryAttribute[]>(`${ADMIN}/categories/${id}/attributes`, { signal }),
  /** Полная замена набора характеристик категории. */
  setAttributes: (id: number, items: CategoryAttributeItem[]) =>
    adminRequest<CategoryAttribute[]>(`${ADMIN}/categories/${id}/attributes`, {
      method: 'PUT',
      body: { items },
    }),
};

export const requestsApi = {
  list: (query: RequestListQuery, { signal }: Signal = {}) =>
    adminRequest<RequestPage>(`${ADMIN}/requests`, { query, signal }),
  /** Карточка целиком: позиции, комментарии и история статусов. */
  get: (id: number, { signal }: Signal = {}) =>
    adminRequest<RequestDetail>(`${ADMIN}/requests/${id}`, { signal }),
  /** Возвращает обновлённую карточку — перечитывать её не нужно. */
  updateStatus: (id: number, body: RequestStatusUpdate) =>
    adminRequest<RequestDetail>(`${ADMIN}/requests/${id}/status`, { method: 'PATCH', body }),
  addComment: (id: number, body: RequestCommentCreate) =>
    adminRequest<RequestComment>(`${ADMIN}/requests/${id}/comments`, { method: 'POST', body }),
  /** Файл, приложенный клиентом к запросу КП, — всегда скачиванием. */
  downloadAttachment: (id: number, attachmentId: number, { signal }: Signal = {}) =>
    adminDownload(`${ADMIN}/requests/${id}/attachments/${attachmentId}`, { signal }),
};

/** Справочник регионов — публичный, токен не нужен. */
export const regionsApi = {
  list: ({ signal }: Signal = {}) => rawRequest<Region[]>('/api/v1/public/regions', { signal }),
};

/** Счётчики каталога одним запросом: карточки без фото и цен, наличие. */
export const catalogApi = {
  summary: ({ signal }: Signal = {}) =>
    adminRequest<CatalogSummary>(`${ADMIN}/catalog/summary`, { signal }),
};

/** Остатки по товарам — только чтение; правка — PUT /products/{id}/stock. */
export const stockApi = {
  list: (query: StockListQuery, { signal }: Signal = {}) =>
    adminRequest<ProductStockPage>(`${ADMIN}/stock`, { query, signal }),
};

/** Склады. Удаления нет: склад отключается через is_active, код неизменяем. */
export const warehousesApi = {
  list: (query: WarehouseListQuery, { signal }: Signal = {}) =>
    adminRequest<WarehousePage>(`${ADMIN}/warehouses`, { query, signal }),
  /** Все склады для фильтров: их единицы, страницы проходятся по 60. */
  listAll: async ({ signal }: Signal = {}): Promise<Warehouse[]> => {
    const items: Warehouse[] = [];
    for (let page = 1; page <= 50; page += 1) {
      const result = await adminRequest<WarehousePage>(`${ADMIN}/warehouses`, {
        query: { page, page_size: 60 },
        signal,
      });
      items.push(...result.items);
      if (page >= result.pages) break;
    }
    return items;
  },
  create: (body: WarehouseCreate) =>
    adminRequest<Warehouse>(`${ADMIN}/warehouses`, { method: 'POST', body }),
  update: (id: number, body: WarehouseUpdate) =>
    adminRequest<Warehouse>(`${ADMIN}/warehouses/${id}`, { method: 'PATCH', body }),
};

/** Состояние интеграций: только безопасные сведения, без реквизитов. */
export const integrationApi = {
  status: ({ signal }: Signal = {}) =>
    adminRequest<IntegrationStatus>(`${ADMIN}/integration/status`, { signal }),
};

export const auditApi = {
  list: (query: AuditLogQuery, { signal }: Signal = {}) =>
    adminRequest<AuditLogPage>(`${ADMIN}/audit`, { query, signal }),
};

/**
 * Импорт и экспорт каталога в XLSX (этап 5E).
 *
 * Разбор и проверку файла делает backend: фронтенд только отправляет
 * книгу и показывает отчёт. На подтверждение файл уходит повторно —
 * сервер его не хранит и сверяет SHA-256 с предпросмотром.
 */
export const importsApi = {
  exportCatalog: ({ signal }: Signal = {}) => adminDownload(`${ADMIN}/catalog/export`, { signal }),
  template: ({ signal }: Signal = {}) =>
    adminDownload(`${ADMIN}/catalog/imports/template`, { signal }),
  /** Каталог не меняет: ошибки данных приходят в теле ответа (valid=false). */
  preview: (file: File, { signal }: Signal = {}) =>
    adminUpload<ImportPreview>(`${ADMIN}/catalog/imports/preview`, file, { signal }),
  /** Тот же файл, что был на предпросмотре, — иначе 409 import_file_mismatch. */
  commit: (jobUuid: string, file: File, { signal }: Signal = {}) =>
    adminUpload<ImportCommitResult>(`${ADMIN}/catalog/imports/${jobUuid}/commit`, file, { signal }),
  history: (query: ImportListQuery, { signal }: Signal = {}) =>
    adminRequest<ImportJobPage>(`${ADMIN}/catalog/imports`, { query, signal }),
  get: (jobUuid: string, { signal }: Signal = {}) =>
    adminRequest<ImportJobDetail>(`${ADMIN}/catalog/imports/${jobUuid}`, { signal }),
};

/**
 * Массовый импорт: ZIP с products.xlsx, фото и схемами.
 *
 * Архив идёт мимо API — PUT по presigned-ссылке прямо в хранилище.
 * Проверку и применение выполняет воркер: экран опрашивает `get`,
 * пока статус не станет итоговым.
 */
export const bundleApi = {
  template: ({ signal }: Signal = {}) =>
    adminDownload(`${ADMIN}/catalog/bundle-imports/template`, { signal }),
  example: ({ signal }: Signal = {}) =>
    adminDownload(`${ADMIN}/catalog/bundle-imports/example`, { signal }),
  create: (body: { filename: string; size_bytes: number }) =>
    adminRequest<BundleUploadCreated>(`${ADMIN}/catalog/bundle-imports`, {
      method: 'POST',
      body,
    }),
  check: (jobUuid: string) =>
    adminRequest<BundleJob>(`${ADMIN}/catalog/bundle-imports/${jobUuid}/check`, {
      method: 'POST',
    }),
  get: (jobUuid: string, { signal }: Signal = {}) =>
    adminRequest<BundleJob>(`${ADMIN}/catalog/bundle-imports/${jobUuid}`, { signal }),
  commit: (jobUuid: string) =>
    adminRequest<BundleJob>(`${ADMIN}/catalog/bundle-imports/${jobUuid}/commit`, {
      method: 'POST',
    }),
  cancel: (jobUuid: string) =>
    adminRequest<BundleJob>(`${ADMIN}/catalog/bundle-imports/${jobUuid}`, { method: 'DELETE' }),
  report: (jobUuid: string, { signal }: Signal = {}) =>
    adminDownload(`${ADMIN}/catalog/bundle-imports/${jobUuid}/report`, { signal }),
};

/** Сотрудники: список, карточка, заведение и изменение. Email неизменяем. */
export const usersApi = {
  list: (query: UserListQuery, { signal }: Signal = {}) =>
    adminRequest<UserPage>(`${ADMIN}/users`, { query, signal }),
  /** Матрица «роль → права» из backend: своей копии фронтенд не держит. */
  roles: ({ signal }: Signal = {}) =>
    adminRequest<RolePermissions[]>(`${ADMIN}/users/roles`, { signal }),
  get: (uuid: string, { signal }: Signal = {}) =>
    adminRequest<AdminUser>(`${ADMIN}/users/${uuid}`, { signal }),
  create: (body: UserCreate) => adminRequest<AdminUser>(`${ADMIN}/users`, { method: 'POST', body }),
  update: (uuid: string, body: UserUpdate) =>
    adminRequest<AdminUser>(`${ADMIN}/users/${uuid}`, { method: 'PATCH', body }),
};

export const contentApi = {
  list: ({ signal }: Signal = {}) =>
    adminRequest<ContentSectionSummary[]>(`${ADMIN}/content`, { signal }),
  get: <K extends ContentSectionKey>(key: K, { signal }: Signal = {}) =>
    adminRequest<ContentSectionRead<K>>(`${ADMIN}/content/${key}`, { signal }),
  /** Раздел сохраняется целиком: backend заменяет документ переданным. */
  save: <K extends ContentSectionKey>(key: K, body: ContentSectionData<K>) =>
    adminRequest<ContentSectionRead<K>>(`${ADMIN}/content/${key}`, { method: 'PUT', body }),
};
