/**
 * Подписи значений перечислений backend.
 *
 * Ключи типизированы сгенерированными union-типами: если backend
 * добавит статус, `Record<RequestStatus, …>` перестанет компилироваться,
 * и новый статус не потеряется в интерфейсе молча. Списки значений для
 * фильтров строятся из этих же объектов, а не пишутся отдельно.
 */

import type {
  ImportJobStatus,
  MediaStatus,
  PricingType,
  ProductStatus,
  PublicAvailability,
  RequestKind,
  RequestSource,
  RequestStatus,
} from '@/lib/api/types';

export type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger' | 'accent';

export type EnumMeta = { label: string; tone: Tone };

export const REQUEST_STATUS: Record<RequestStatus, EnumMeta> = {
  NEW: { label: 'Новая', tone: 'accent' },
  IN_PROGRESS: { label: 'В работе', tone: 'info' },
  WAITING_CLIENT: { label: 'Ждём клиента', tone: 'warning' },
  QUOTE_SENT: { label: 'КП отправлено', tone: 'info' },
  APPROVED: { label: 'Согласована', tone: 'success' },
  COMPLETED: { label: 'Выполнена', tone: 'success' },
  CANCELLED: { label: 'Отменена', tone: 'neutral' },
  SPAM: { label: 'Спам', tone: 'danger' },
};

export const REQUEST_KIND: Record<RequestKind, string> = {
  CART: 'С позициями',
  GENERAL: 'Без позиций',
};

export const REQUEST_SOURCE: Record<RequestSource, string> = {
  CATALOG_CART: 'Корзина сайта',
  PRODUCT_PAGE: 'Страница товара',
  NOT_FOUND_FORM: 'Форма «Не нашли товар»',
  CONTACT_FORM: 'Форма контактов',
  ADMIN: 'Создана сотрудником',
  QUICK_CALLBACK: 'Обратный звонок',
  ONE_CLICK: 'Заказ в 1 клик',
  SKU_LIST: 'Заказ по артикулам',
  QUOTE_REQUEST: 'Запрос КП',
};

/**
 * Быстрый заказ — отдельной меткой в списке: звонок и запрос КП
 * обрабатываются иначе, чем собранная корзина.
 */
export const REQUEST_SOURCE_TONE: Partial<Record<RequestSource, Tone>> = {
  QUICK_CALLBACK: 'warning',
  ONE_CLICK: 'accent',
  SKU_LIST: 'info',
  QUOTE_REQUEST: 'success',
};

export const PRODUCT_STATUS: Record<ProductStatus, EnumMeta> = {
  DRAFT: { label: 'Черновик', tone: 'neutral' },
  PUBLISHED: { label: 'Опубликован', tone: 'success' },
  ARCHIVED: { label: 'В архиве', tone: 'warning' },
};

export const PRICING_TYPE: Record<PricingType, string> = {
  FIXED: 'Фиксированная',
  FROM: 'От',
  TIERED: 'По ступеням',
  ON_REQUEST: 'По запросу',
};

export const AVAILABILITY: Record<PublicAvailability, EnumMeta> = {
  IN_STOCK: { label: 'В наличии', tone: 'success' },
  OUT_OF_STOCK: { label: 'Нет в наличии', tone: 'danger' },
  ON_REQUEST: { label: 'Под заказ', tone: 'warning' },
};

export const MEDIA_STATUS: Record<MediaStatus, EnumMeta> = {
  PENDING: { label: 'Ожидает загрузки', tone: 'neutral' },
  PROCESSING: { label: 'Обработка', tone: 'info' },
  READY: { label: 'Готово', tone: 'success' },
  FAILED: { label: 'Ошибка', tone: 'danger' },
};

export const IMPORT_STATUS: Record<ImportJobStatus, EnumMeta> = {
  UPLOADING: { label: 'Загрузка', tone: 'neutral' },
  CHECKING: { label: 'Проверяется', tone: 'info' },
  VALID: { label: 'Проверен', tone: 'info' },
  INVALID: { label: 'Есть ошибки', tone: 'danger' },
  COMMITTED: { label: 'Применён', tone: 'success' },
  FAILED: { label: 'Не применён', tone: 'warning' },
  APPLYING: { label: 'Применяется', tone: 'info' },
  CANCELLED: { label: 'Отменён', tone: 'neutral' },
};

/** Значения перечисления в порядке объявления — для фильтров и селектов. */
export function enumOptions<K extends string>(
  meta: Record<K, EnumMeta | string>,
): { value: K; label: string }[] {
  return (Object.keys(meta) as K[]).map((value) => {
    const item = meta[value];
    return { value, label: typeof item === 'string' ? item : item.label };
  });
}
