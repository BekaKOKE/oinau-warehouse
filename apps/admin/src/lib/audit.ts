/**
 * Журнал аудита: подписи действий, фильтры и разбор поля `changes`.
 *
 * Список действий — копия констант backend (`*AuditAction` в модулях).
 * Копия нужна ровно для одного: показать человеку «Товар создан»
 * вместо `catalog.product_created`. Решений по ней не принимается,
 * а неизвестное действие показывается как есть — новое событие
 * backend не потеряется и не сломает экран.
 *
 * Поиска по журналу backend не поддерживает: фильтры — только те,
 * что объявлены в GET /admin/audit.
 */

import type { AuditLogEntry, AuditLogQuery } from '@/lib/api/types';
import type { Tone } from '@/lib/labels';
import { dayEnd, dayStart } from '@/lib/requests';

export const AUDIT_PAGE_SIZE = 30;

// --------------------------------------------------------------- сущности

/** entity_type → раздел, о котором рассказывает запись. */
export const AUDIT_ENTITY_LABELS: Record<string, string> = {
  product: 'Товар',
  product_pricing: 'Цены товара',
  product_stock: 'Остатки товара',
  product_availability: 'Наличие товара',
  category: 'Категория',
  category_attributes: 'Характеристики категории',
  attribute: 'Характеристика',
  attribute_option: 'Вариант значения',
  warehouse: 'Склад',
  media_file: 'Файл',
  request: 'Заявка',
  content_section: 'Раздел сайта',
  import_job: 'Импорт каталога',
  user: 'Сотрудник',
  customer: 'Клиент',
};

export function auditEntityLabel(entityType: string): string {
  return AUDIT_ENTITY_LABELS[entityType] ?? entityType;
}

// --------------------------------------------------------------- действия

type ActionMeta = {
  label: string;
  /** entity_type, с которым backend пишет это действие. */
  entity: string;
  tone: Tone;
};

/** Порядок объявления — порядок в фильтре «Действие». */
export const AUDIT_ACTIONS: Record<string, ActionMeta> = {
  // товары
  'catalog.product_created': { label: 'Товар создан', entity: 'product', tone: 'success' },
  'catalog.product_updated': { label: 'Товар изменён', entity: 'product', tone: 'info' },
  'catalog.product_deleted': { label: 'Товар удалён', entity: 'product', tone: 'danger' },
  'catalog.product_restored': { label: 'Товар восстановлен', entity: 'product', tone: 'success' },
  'catalog.product_categories_replaced': {
    label: 'Категории товара изменены',
    entity: 'product',
    tone: 'info',
  },
  'catalog.product_attributes_replaced': {
    label: 'Характеристики товара изменены',
    entity: 'product',
    tone: 'info',
  },
  'pricing.updated': { label: 'Цены изменены', entity: 'product_pricing', tone: 'info' },
  'inventory.stock_updated': { label: 'Остатки изменены', entity: 'product_stock', tone: 'info' },
  'inventory.availability_override_updated': {
    label: 'Показ наличия переопределён',
    entity: 'product_availability',
    tone: 'warning',
  },
  // категории и характеристики
  'catalog.category_created': { label: 'Категория создана', entity: 'category', tone: 'success' },
  'catalog.category_updated': { label: 'Категория изменена', entity: 'category', tone: 'info' },
  'catalog.category_deleted': { label: 'Категория удалена', entity: 'category', tone: 'danger' },
  'catalog.category_restored': {
    label: 'Категория восстановлена',
    entity: 'category',
    tone: 'success',
  },
  'catalog.category_attributes_assigned': {
    label: 'Характеристики категории назначены',
    entity: 'category_attributes',
    tone: 'info',
  },
  'catalog.attribute_created': {
    label: 'Характеристика создана',
    entity: 'attribute',
    tone: 'success',
  },
  'catalog.attribute_updated': {
    label: 'Характеристика изменена',
    entity: 'attribute',
    tone: 'info',
  },
  'catalog.attribute_deleted': {
    label: 'Характеристика удалена',
    entity: 'attribute',
    tone: 'danger',
  },
  'catalog.attribute_option_created': {
    label: 'Вариант значения добавлен',
    entity: 'attribute_option',
    tone: 'success',
  },
  'catalog.attribute_option_updated': {
    label: 'Вариант значения изменён',
    entity: 'attribute_option',
    tone: 'info',
  },
  'catalog.attribute_option_deleted': {
    label: 'Вариант значения удалён',
    entity: 'attribute_option',
    tone: 'danger',
  },
  // склады
  'inventory.warehouse_created': { label: 'Склад создан', entity: 'warehouse', tone: 'success' },
  'inventory.warehouse_updated': { label: 'Склад изменён', entity: 'warehouse', tone: 'info' },
  // медиа
  'media.upload_requested': { label: 'Запрошена загрузка', entity: 'media_file', tone: 'neutral' },
  'media.upload_completed': { label: 'Файл загружен', entity: 'media_file', tone: 'success' },
  'media.upload_rejected': { label: 'Загрузка отклонена', entity: 'media_file', tone: 'danger' },
  'media.processed': { label: 'Файл обработан', entity: 'media_file', tone: 'success' },
  'media.processing_failed': {
    label: 'Обработка не удалась',
    entity: 'media_file',
    tone: 'danger',
  },
  'media.deleted': { label: 'Файл удалён', entity: 'media_file', tone: 'danger' },
  'media.product_image_attached': {
    label: 'Изображение привязано',
    entity: 'product',
    tone: 'info',
  },
  'media.product_image_updated': {
    label: 'Изображение изменено',
    entity: 'product',
    tone: 'info',
  },
  'media.product_image_detached': {
    label: 'Изображение отвязано',
    entity: 'product',
    tone: 'warning',
  },
  'media.product_images_reordered': {
    label: 'Порядок изображений изменён',
    entity: 'product',
    tone: 'info',
  },
  'media.product_main_image_changed': {
    label: 'Главное изображение изменено',
    entity: 'product',
    tone: 'info',
  },
  // заявки
  'request.created': { label: 'Заявка создана', entity: 'request', tone: 'success' },
  'request.status_updated': { label: 'Статус заявки изменён', entity: 'request', tone: 'info' },
  'request.comment_created': { label: 'Комментарий добавлен', entity: 'request', tone: 'neutral' },
  // сайт
  'content.section_updated': {
    label: 'Раздел сайта сохранён',
    entity: 'content_section',
    tone: 'info',
  },
  // импорт
  'catalog_import.previewed': { label: 'Файл проверен', entity: 'import_job', tone: 'neutral' },
  'catalog_import.committed': { label: 'Импорт применён', entity: 'import_job', tone: 'success' },
  'catalog_import.commit_failed': {
    label: 'Импорт не применён',
    entity: 'import_job',
    tone: 'danger',
  },
  // сотрудники
  'user.created': { label: 'Сотрудник заведён', entity: 'user', tone: 'success' },
  'user.updated': { label: 'Сотрудник изменён', entity: 'user', tone: 'info' },
  'user.password_reset': { label: 'Пароль сотрудника сброшен', entity: 'user', tone: 'warning' },
  'auth.login_success': { label: 'Вход в админку', entity: 'user', tone: 'neutral' },
  'auth.login_failed': { label: 'Неудачная попытка входа', entity: 'user', tone: 'warning' },
  'auth.login_blocked': { label: 'Вход заблокирован', entity: 'user', tone: 'danger' },
  'auth.logout': { label: 'Выход из админки', entity: 'user', tone: 'neutral' },
  'auth.token_refreshed': { label: 'Сессия продлена', entity: 'user', tone: 'neutral' },
  'auth.token_reuse_detected': {
    label: 'Повторное использование токена',
    entity: 'user',
    tone: 'danger',
  },
  'auth.password_changed': { label: 'Пароль изменён', entity: 'user', tone: 'warning' },
  // клиенты
  'customer.registered': { label: 'Клиент зарегистрирован', entity: 'customer', tone: 'success' },
  'customer.email_verified': { label: 'Email клиента подтверждён', entity: 'customer', tone: 'success' }, // prettier-ignore
  'customer.profile_updated': {
    label: 'Профиль клиента изменён',
    entity: 'customer',
    tone: 'info',
  },
  'customer.login_success': { label: 'Вход клиента', entity: 'customer', tone: 'neutral' },
  'customer.login_failed': {
    label: 'Неудачный вход клиента',
    entity: 'customer',
    tone: 'warning',
  },
  'customer.login_blocked': { label: 'Вход клиента заблокирован', entity: 'customer', tone: 'danger' }, // prettier-ignore
  'customer.logout': { label: 'Выход клиента', entity: 'customer', tone: 'neutral' },
  'customer.token_refreshed': { label: 'Сессия клиента продлена', entity: 'customer', tone: 'neutral' }, // prettier-ignore
  'customer.token_reuse_detected': {
    label: 'Повторный токен клиента',
    entity: 'customer',
    tone: 'danger',
  },
  'customer.password_reset_requested': {
    label: 'Клиент запросил сброс пароля',
    entity: 'customer',
    tone: 'neutral',
  },
  'customer.password_reset': { label: 'Пароль клиента сброшен', entity: 'customer', tone: 'warning' }, // prettier-ignore
};

export function auditActionLabel(action: string): string {
  return AUDIT_ACTIONS[action]?.label ?? action;
}

export function auditActionTone(action: string): Tone {
  return AUDIT_ACTIONS[action]?.tone ?? 'neutral';
}

/** Варианты фильтра «Действие»; при выбранном разделе — только его действия. */
export function actionOptions(entityType: string): { value: string; label: string }[] {
  return Object.entries(AUDIT_ACTIONS)
    .filter(([, meta]) => !entityType || meta.entity === entityType)
    .map(([value, meta]) => ({ value, label: meta.label }));
}

export function entityOptions(): { value: string; label: string }[] {
  return Object.entries(AUDIT_ENTITY_LABELS).map(([value, label]) => ({ value, label }));
}

// ----------------------------------------------------------------- актор

/** audit_log.actor — кто выполнил действие, если это не сотрудник. */
export const AUDIT_ACTOR_LABELS: Record<string, string> = {
  user: 'Сотрудник',
  customer: 'Клиент',
  public: 'Посетитель сайта',
  import: 'Импорт из файла',
  system: 'Система',
};

export function auditActorLabel(actor: string): string {
  return AUDIT_ACTOR_LABELS[actor] ?? actor;
}

export function actorOptions(): { value: string; label: string }[] {
  return Object.entries(AUDIT_ACTOR_LABELS).map(([value, label]) => ({ value, label }));
}

// ---------------------------------------------------------------- ссылки

/**
 * Куда вести из записи журнала.
 *
 * Только туда, где объект действительно открывается по числовому id:
 * у файла, импорта и сотрудника адрес строится по uuid, которого
 * в журнале нет, поэтому ссылки для них нет.
 */
export function auditEntityHref(entry: AuditLogEntry): string | null {
  if (entry.entity_id === null || entry.entity_id === undefined) return null;
  switch (entry.entity_type) {
    case 'product':
    case 'product_pricing':
    case 'product_stock':
    case 'product_availability':
      return `/products/${entry.entity_id}`;
    case 'request':
      return `/requests/${entry.entity_id}`;
    case 'category':
    case 'category_attributes':
      return `/categories?id=${entry.entity_id}`;
    default:
      return null;
  }
}

// -------------------------------------------------------------- изменения

/**
 * Значения, которые не показываются, даже если однажды попадут в журнал.
 *
 * Сейчас backend их туда не пишет (пароль хешируется и не аудируется,
 * ip_hash не отдаётся вовсе). Проверка — страховка: журнал читают
 * администраторы, а не владелец данных, и «случайно показать секрет»
 * здесь дороже, чем «случайно скрыть безобидное поле».
 */
const SECRET_KEY_PATTERN = /password|secret|token|storage_key|ip_hash|api_key|credential/i;

export function isSecretKey(key: string): boolean {
  return SECRET_KEY_PATTERN.test(key);
}

export type ChangeRow = {
  key: string;
  label: string;
  /** Пара old → new, если backend записал изменение именно так. */
  before?: string;
  after?: string;
  /** Иначе — одиночное значение. */
  value?: string;
  secret: boolean;
};

/** Подписи часто встречающихся полей; остальные показываются как есть. */
const FIELD_LABELS: Record<string, string> = {
  sku: 'Артикул',
  slug: 'Слаг',
  name: 'Название',
  status: 'Статус',
  is_active: 'Активен',
  is_featured: 'Рекомендуемый',
  unit: 'Единица',
  price: 'Цена',
  pricing_type: 'Тип цены',
  currency: 'Валюта',
  tiers: 'Ступени цены',
  quantity: 'Количество',
  warehouse: 'Склад',
  stock_display_override: 'Переопределение наличия',
  parent_id: 'Родитель',
  sort_order: 'Порядок',
  role: 'Роль',
  email: 'Email',
  full_name: 'Имя',
  phone: 'Телефон',
  comment: 'Комментарий',
  number: 'Номер',
  region_id: 'Регион',
  items_count: 'Позиций',
  total_estimate: 'Сумма',
  section: 'Раздел',
  filename: 'Файл',
  original_filename: 'Исходное имя файла',
  content_type: 'Тип файла',
  size_bytes: 'Размер, байт',
  declared_size: 'Заявленный размер, байт',
  actual_size: 'Фактический размер, байт',
  failure_reason: 'Причина отказа',
  purpose: 'Назначение',
  import_job: 'Задача импорта',
  job_uuid: 'UUID задачи',
  file_size: 'Размер файла, байт',
  file_sha256: 'Контрольная сумма файла',
  rows_total: 'Строк в файле',
  error_count: 'Ошибок',
  warning_count: 'Предупреждений',
  attribute_options: 'Варианты значений',
  reserved: 'Резерв',
  available: 'Доступно',
  failed_login_count: 'Неудачных входов',
  revoked_sessions: 'Отозвано сессий',
  media_uuid: 'UUID файла',
  image_id: 'Изображение',
  is_main: 'Главное',
  kind: 'Вид',
  uuid: 'UUID',
  products: 'Товары',
  categories: 'Категории',
  attributes: 'Характеристики',
  created: 'Создано',
  updated: 'Изменено',
};

export function fieldLabel(key: string): string {
  return FIELD_LABELS[key] ?? key;
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function formatChangeValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'boolean') return value ? 'да' : 'нет';
  if (typeof value === 'number' || typeof value === 'string') return String(value) || '—';
  return JSON.stringify(value, null, 2);
}

/** `changes` → строки таблицы. Форма {"old": …, "new": …} разбирается в пару. */
export function changeRows(changes: Record<string, unknown>): ChangeRow[] {
  return Object.entries(changes).map(([key, value]) => {
    const secret = isSecretKey(key);
    const base = { key, label: fieldLabel(key), secret };
    if (secret) return { ...base, value: 'скрыто' };
    if (isPlainRecord(value) && ('old' in value || 'new' in value)) {
      return { ...base, before: formatChangeValue(value.old), after: formatChangeValue(value.new) };
    }
    return { ...base, value: formatChangeValue(value) };
  });
}

/** Короткая сводка для строки таблицы: перечисление изменённых полей. */
export function changesSummary(changes: Record<string, unknown>, limit = 3): string {
  const keys = Object.keys(changes);
  if (keys.length === 0) return '';
  const shown = keys.slice(0, limit).map(fieldLabel).join(', ');
  return keys.length > limit ? `${shown} и ещё ${keys.length - limit}` : shown;
}

// --------------------------------------------------------------- фильтры

export type AuditFilters = {
  /** Поиска по журналу backend не поддерживает; поле требует useUrlFilters. */
  search: string;
  action: string;
  entityType: string;
  entityId: string;
  actor: string;
  userUuid: string;
  requestId: string;
  /** Даты дня (input type=date), как в заявках. */
  dateFrom: string;
  dateTo: string;
  page: number;
};

export const DEFAULT_AUDIT_FILTERS: AuditFilters = {
  search: '',
  action: '',
  entityType: '',
  entityId: '',
  actor: '',
  userUuid: '',
  requestId: '',
  dateFrom: '',
  dateTo: '',
  page: 1,
};

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function parseAuditFilters(params: URLSearchParams): AuditFilters {
  const entityId = params.get('entity_id') ?? '';
  const userUuid = params.get('user') ?? '';
  const dateFrom = params.get('from') ?? '';
  const dateTo = params.get('to') ?? '';
  const page = Number.parseInt(params.get('page') ?? '', 10);
  return {
    search: '',
    action: (params.get('action') ?? '').slice(0, 64),
    entityType: (params.get('entity') ?? '').slice(0, 64),
    entityId: /^\d{1,18}$/.test(entityId) ? entityId : '',
    actor: (params.get('actor') ?? '').slice(0, 32),
    userUuid: UUID_RE.test(userUuid) ? userUuid : '',
    requestId: (params.get('request_id') ?? '').slice(0, 64),
    dateFrom: DATE_RE.test(dateFrom) ? dateFrom : '',
    dateTo: DATE_RE.test(dateTo) ? dateTo : '',
    page: Number.isFinite(page) && page > 0 ? page : 1,
  };
}

export function serializeAuditFilters(filters: AuditFilters): string {
  const params = new URLSearchParams();
  if (filters.action) params.set('action', filters.action);
  if (filters.entityType) params.set('entity', filters.entityType);
  if (filters.entityId) params.set('entity_id', filters.entityId);
  if (filters.actor) params.set('actor', filters.actor);
  if (filters.userUuid) params.set('user', filters.userUuid);
  if (filters.requestId) params.set('request_id', filters.requestId);
  if (filters.dateFrom) params.set('from', filters.dateFrom);
  if (filters.dateTo) params.set('to', filters.dateTo);
  if (filters.page > 1) params.set('page', String(filters.page));
  const query = params.toString();
  return query ? `?${query}` : '';
}

export function hasActiveAuditFilters(filters: AuditFilters): boolean {
  return Boolean(
    filters.action ||
    filters.entityType ||
    filters.entityId ||
    filters.actor ||
    filters.userUuid ||
    filters.requestId ||
    filters.dateFrom ||
    filters.dateTo,
  );
}

/** Период задан наоборот — backend ответит 422, подскажем заранее. */
export function auditDateRangeError(filters: AuditFilters): string | null {
  if (filters.dateFrom && filters.dateTo && filters.dateFrom > filters.dateTo) {
    return 'Дата «с» позже даты «по»';
  }
  return null;
}

export function auditListQuery(filters: AuditFilters): AuditLogQuery {
  return {
    action: filters.action || undefined,
    entity_type: filters.entityType || undefined,
    entity_id: filters.entityId ? Number(filters.entityId) : undefined,
    actor: filters.actor || undefined,
    user_uuid: filters.userUuid || undefined,
    request_id: filters.requestId || undefined,
    created_from: filters.dateFrom ? dayStart(filters.dateFrom) : undefined,
    created_to: filters.dateTo ? dayEnd(filters.dateTo) : undefined,
    page: filters.page,
    page_size: AUDIT_PAGE_SIZE,
  };
}
