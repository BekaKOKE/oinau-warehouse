/**
 * Кабинет клиента — /api/v1/customer.
 *
 * Все запросы идут через `customerRequest`: он подставляет access-токен
 * и один раз обновляет сессию на 401. Идентификатор клиента на backend
 * берётся из токена, поэтому ни в одном запросе его нет.
 */

import type {
  CustomerFavorite,
  CustomerFavoritePage,
  CustomerNotification,
  CustomerProfile,
  CustomerProfileUpdate,
  CustomerRequestCreate,
  CustomerRequestDetail,
  CustomerRequestPage,
  NotificationPage,
  ProjectCreate,
  ProjectDetail,
  ProjectItemAdd,
  ProjectPage,
  ProjectUpdate,
  RequestCreated,
  UnreadCount,
} from '@oinau/api-types';

import { customerRequest } from '@/lib/cabinet/session';

const BASE = '/api/v1/customer';

export const CABINET_PAGE_SIZE = 20;

/** Максимум backend на страницу — для выборки всех артикулов избранного. */
export const MAX_PAGE_SIZE = 60;

type PageQuery = { page?: number; pageSize?: number };

function pageParams({ page = 1, pageSize = CABINET_PAGE_SIZE }: PageQuery) {
  return { page, page_size: pageSize };
}

const segment = (value: string) => encodeURIComponent(value);

// ------------------------------------------------------------------ профиль

export function fetchProfile(): Promise<CustomerProfile> {
  return customerRequest<CustomerProfile>(`${BASE}/profile`);
}

export function updateProfile(payload: CustomerProfileUpdate): Promise<CustomerProfile> {
  return customerRequest<CustomerProfile>(`${BASE}/profile`, { method: 'PATCH', body: payload });
}

// ---------------------------------------------------------------- избранное

export function fetchFavorites(query: PageQuery = {}): Promise<CustomerFavoritePage> {
  return customerRequest<CustomerFavoritePage>(`${BASE}/favorites`, { query: pageParams(query) });
}

/** Все артикулы избранного — для сердечек в каталоге. */
export async function fetchAllFavoriteSkus(): Promise<string[]> {
  const skus: string[] = [];
  for (let page = 1; page <= 50; page += 1) {
    const result = await fetchFavorites({ page, pageSize: MAX_PAGE_SIZE });
    skus.push(...result.items.map((item) => item.sku));
    if (page >= result.pages) break;
  }
  return skus;
}

export function addFavorite(sku: string): Promise<CustomerFavorite> {
  return customerRequest<CustomerFavorite>(`${BASE}/favorites`, {
    method: 'POST',
    body: { sku },
  });
}

export function removeFavorite(sku: string): Promise<void> {
  return customerRequest<void>(`${BASE}/favorites/${segment(sku)}`, { method: 'DELETE' });
}

// ------------------------------------------------------------------- заявки

export function fetchCustomerRequests(query: PageQuery = {}): Promise<CustomerRequestPage> {
  return customerRequest<CustomerRequestPage>(`${BASE}/requests`, { query: pageParams(query) });
}

export function fetchCustomerRequest(number: string): Promise<CustomerRequestDetail> {
  return customerRequest<CustomerRequestDetail>(`${BASE}/requests/${segment(number)}`);
}

// ------------------------------------------------------------------ проекты

export function fetchProjects(query: PageQuery = {}): Promise<ProjectPage> {
  return customerRequest<ProjectPage>(`${BASE}/projects`, { query: pageParams(query) });
}

export function fetchProject(uuid: string): Promise<ProjectDetail> {
  return customerRequest<ProjectDetail>(`${BASE}/projects/${segment(uuid)}`);
}

export function createProject(payload: ProjectCreate): Promise<ProjectDetail> {
  return customerRequest<ProjectDetail>(`${BASE}/projects`, { method: 'POST', body: payload });
}

export function updateProject(uuid: string, payload: ProjectUpdate): Promise<ProjectDetail> {
  return customerRequest<ProjectDetail>(`${BASE}/projects/${segment(uuid)}`, {
    method: 'PATCH',
    body: payload,
  });
}

export function deleteProject(uuid: string): Promise<void> {
  return customerRequest<void>(`${BASE}/projects/${segment(uuid)}`, { method: 'DELETE' });
}

export function addProjectItem(uuid: string, payload: ProjectItemAdd): Promise<ProjectDetail> {
  return customerRequest<ProjectDetail>(`${BASE}/projects/${segment(uuid)}/items`, {
    method: 'POST',
    body: payload,
  });
}

export function removeProjectItem(uuid: string, sku: string): Promise<void> {
  return customerRequest<void>(`${BASE}/projects/${segment(uuid)}/items/${segment(sku)}`, {
    method: 'DELETE',
  });
}

// -------------------------------------------------------------- уведомления

export function fetchNotifications(
  query: PageQuery & { unread?: boolean } = {},
): Promise<NotificationPage> {
  return customerRequest<NotificationPage>(`${BASE}/notifications`, {
    query: { ...pageParams(query), unread: query.unread || undefined },
  });
}

export function fetchUnreadCount(): Promise<UnreadCount> {
  return customerRequest<UnreadCount>(`${BASE}/notifications/unread-count`);
}

export function markNotificationRead(uuid: string): Promise<CustomerNotification> {
  return customerRequest<CustomerNotification>(`${BASE}/notifications/${segment(uuid)}/read`, {
    method: 'POST',
  });
}

export function markAllNotificationsRead(): Promise<UnreadCount> {
  return customerRequest<UnreadCount>(`${BASE}/notifications/read-all`, { method: 'POST' });
}

/**
 * Заявка из кабинета: та же форма, что у публичной, но привязывается
 * к аккаунту и видна в истории. Ключ идемпотентности защищает от дубля
 * при повторе после обрыва сети.
 */
export function submitCustomerRequest(
  payload: CustomerRequestCreate,
  idempotencyKey: string,
): Promise<RequestCreated> {
  return customerRequest<RequestCreated>(`${BASE}/requests`, {
    method: 'POST',
    body: payload,
    idempotencyKey,
  });
}
