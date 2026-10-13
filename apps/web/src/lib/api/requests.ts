/**
 * Отправка заявки и справочник регионов.
 *
 * Заявка уходит из браузера: форму заполняет посетитель, и ограничение
 * частоты на backend считает именно его IP. Прокси через серверный
 * компонент Next.js превратил бы всех посетителей в одного клиента.
 */

import type { Region, RequestCreate, RequestCreated } from '@oinau/api-types';

import { apiRequest } from '@/lib/api/client';

export async function fetchRegions(): Promise<Region[]> {
  return apiRequest<Region[]>('/api/v1/public/regions', { revalidate: 3600 });
}

/**
 * `idempotencyKey` генерируется при открытии формы: повтор после
 * обрыва сети возвращает уже созданную заявку, а не создаёт вторую.
 */
export async function submitRequest(
  payload: RequestCreate,
  idempotencyKey: string,
): Promise<RequestCreated> {
  return apiRequest<RequestCreated>('/api/v1/public/requests', {
    method: 'POST',
    body: payload,
    idempotencyKey,
  });
}

export function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `req-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}
