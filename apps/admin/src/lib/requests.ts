/**
 * Правила интерфейса раздела заявок.
 *
 * Здесь нет бизнес-логики заявок: переходы между статусами backend не
 * ограничивает (движка workflow нет), поэтому интерфейс предлагает любой
 * статус из перечисления backend, кроме текущего. Отдельно выделены лишь
 * «необратимые по смыслу» статусы — перед ними спрашиваем подтверждение.
 */

import type {
  RequestAdminSort,
  RequestListQuery,
  RequestSource,
  RequestStatus,
} from '@/lib/api/types';
import { TIME_ZONE } from '@/lib/format';
import { enumOptions, REQUEST_SOURCE, REQUEST_STATUS } from '@/lib/labels';

export const REQUEST_PAGE_SIZE = 20;

export const REQUEST_SORT_LABELS: Record<RequestAdminSort, string> = {
  newest: 'Сначала новые',
  oldest: 'Сначала старые',
  updated: 'Недавно изменённые',
};

/** Переход в эти статусы (или выход из них) подтверждается. */
const CONFIRM_STATUSES: ReadonlySet<RequestStatus> = new Set<RequestStatus>([
  'COMPLETED',
  'CANCELLED',
  'SPAM',
]);

export function needsStatusConfirm(from: RequestStatus, to: RequestStatus): boolean {
  return from !== to && (CONFIRM_STATUSES.has(to) || CONFIRM_STATUSES.has(from));
}

/** Все статусы backend, кроме текущего, — в порядке объявления перечисления. */
export function statusTargets(current: RequestStatus): { value: RequestStatus; label: string }[] {
  return enumOptions(REQUEST_STATUS).filter((option) => option.value !== current);
}

// ------------------------------------------------------------- фильтры

export type RequestFilters = {
  search: string;
  status: RequestStatus | '';
  /** Откуда пришла заявка: корзина, звонок, список артикулов, запрос КП. */
  source: RequestSource | '';
  sort: RequestAdminSort;
  regionId: string;
  /** Даты дня в формате YYYY-MM-DD (поле input type=date). */
  dateFrom: string;
  dateTo: string;
  page: number;
};

export const DEFAULT_FILTERS: RequestFilters = {
  search: '',
  status: '',
  source: '',
  sort: 'newest',
  regionId: '',
  dateFrom: '',
  dateTo: '',
  page: 1,
};

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function isStatus(value: string): value is RequestStatus {
  return value in REQUEST_STATUS;
}

function isSort(value: string): value is RequestAdminSort {
  return value in REQUEST_SORT_LABELS;
}

function isSource(value: string): value is RequestSource {
  return value in REQUEST_SOURCE;
}

/** Фильтры из адресной строки. Неизвестные значения молча отбрасываются. */
export function filtersFromParams(params: URLSearchParams): RequestFilters {
  const status = params.get('status') ?? '';
  const source = params.get('source') ?? '';
  const sort = params.get('sort') ?? '';
  const page = Number.parseInt(params.get('page') ?? '', 10);
  const regionId = params.get('region_id') ?? '';
  const dateFrom = params.get('from') ?? '';
  const dateTo = params.get('to') ?? '';
  return {
    search: (params.get('search') ?? '').slice(0, 100),
    status: isStatus(status) ? status : '',
    source: isSource(source) ? source : '',
    sort: isSort(sort) ? sort : DEFAULT_FILTERS.sort,
    regionId: /^\d+$/.test(regionId) ? regionId : '',
    dateFrom: DATE_RE.test(dateFrom) ? dateFrom : '',
    dateTo: DATE_RE.test(dateTo) ? dateTo : '',
    page: Number.isFinite(page) && page > 0 ? page : 1,
  };
}

/** Фильтры → строка запроса страницы (значения по умолчанию не пишутся). */
export function filtersToSearch(filters: RequestFilters): string {
  const params = new URLSearchParams();
  if (filters.search.trim()) params.set('search', filters.search.trim());
  if (filters.status) params.set('status', filters.status);
  if (filters.source) params.set('source', filters.source);
  if (filters.sort !== DEFAULT_FILTERS.sort) params.set('sort', filters.sort);
  if (filters.regionId) params.set('region_id', filters.regionId);
  if (filters.dateFrom) params.set('from', filters.dateFrom);
  if (filters.dateTo) params.set('to', filters.dateTo);
  if (filters.page > 1) params.set('page', String(filters.page));
  const query = params.toString();
  return query ? `?${query}` : '';
}

export function hasActiveFilters(filters: RequestFilters): boolean {
  return Boolean(
    filters.search.trim() ||
    filters.status ||
    filters.source ||
    filters.regionId ||
    filters.dateFrom ||
    filters.dateTo,
  );
}

/**
 * Смещение Asia/Almaty на дату, например «+05:00».
 *
 * Берётся из базы часовых поясов браузера, а не зашивается числом:
 * смещение Казахстана уже менялось и может измениться снова.
 */
function almatyOffset(date: string): string {
  const probe = new Date(`${date}T12:00:00Z`);
  const part = new Intl.DateTimeFormat('en-US', { timeZone: TIME_ZONE, timeZoneName: 'longOffset' })
    .formatToParts(probe)
    .find((item) => item.type === 'timeZoneName')?.value;
  const match = part ? /GMT([+-]\d{2}:\d{2})/.exec(part) : null;
  return match?.[1] ?? '+05:00';
}

function nextDay(date: string): string {
  const value = new Date(`${date}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() + 1);
  return value.toISOString().slice(0, 10);
}

/** Начало дня в Алматы — граница «с» (включительно). */
export function dayStart(date: string): string {
  return `${date}T00:00:00${almatyOffset(date)}`;
}

/** Начало следующего дня в Алматы — граница «по» (исключительно). */
export function dayEnd(date: string): string {
  const next = nextDay(date);
  return `${next}T00:00:00${almatyOffset(next)}`;
}

/** Фильтры экрана → query-параметры GET /admin/requests. */
export function filtersToQuery(filters: RequestFilters): RequestListQuery {
  return {
    search: filters.search.trim() || undefined,
    status: filters.status || undefined,
    source: filters.source || undefined,
    sort: filters.sort,
    region_id: filters.regionId ? Number(filters.regionId) : undefined,
    created_from: filters.dateFrom ? dayStart(filters.dateFrom) : undefined,
    created_to: filters.dateTo ? dayEnd(filters.dateTo) : undefined,
    page: filters.page,
    page_size: REQUEST_PAGE_SIZE,
  };
}

/** Период задан наоборот — backend ответит 422, подскажем заранее. */
export function dateRangeError(filters: RequestFilters): string | null {
  if (filters.dateFrom && filters.dateTo && filters.dateFrom > filters.dateTo) {
    return 'Дата «с» позже даты «по»';
  }
  return null;
}

/** Телефон для ссылки tel: — только цифры и плюс. */
export function telHref(phone: string): string {
  return `tel:${phone.replace(/[^\d+]/g, '')}`;
}
