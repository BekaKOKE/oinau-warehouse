/**
 * Быстрый заказ — POST /api/v1/public/quick-requests.
 *
 * Тело — multipart/form-data: к запросу КП прикладывается файл. Поля
 * совпадают со схемой PublicQuickRequestCreate на backend; пустые не
 * отправляются вовсе, лишние backend отвергает (extra=forbid).
 *
 * Вошедший клиент отправляет через кабинет (/customer/quick-requests):
 * заявка попадает в его историю. Как и у обычной заявки, запрос идёт
 * из браузера, чтобы ограничение частоты считало IP посетителя.
 */

import type { QuickRequestCreated, QuickRequestMode } from '@oinau/api-types';

import { apiRequest } from '@/lib/api/client';
import { customerRequest } from '@/lib/cabinet/session';

export type QuickRequestInput = {
  mode: QuickRequestMode;
  name: string;
  phone: string;
  email?: string;
  company?: string;
  bin?: string;
  comment?: string;
  /** SKU_LIST: текст как его вставил клиент — разбирает сервер. */
  skuList?: string;
  /** CALLBACK с карточки товара — «заказ в 1 клик». */
  productSku?: string;
  /** Код цвета товара, если он выбран на странице товара. */
  productColor?: string;
  quantity?: string;
  pageUrl?: string;
  file?: File | null;
};

/** Двадцать мегабайт по мобильной сети — не пятнадцать секунд. */
const UPLOAD_TIMEOUT_MS = 120_000;

export const ATTACHMENT_MAX_MB = 20;
export const ATTACHMENT_EXTENSIONS = [
  'pdf',
  'xls',
  'xlsx',
  'doc',
  'docx',
  'dwg',
  'dxf',
  'csv',
  'jpg',
  'jpeg',
  'png',
] as const;

export function toQuickRequestForm(input: QuickRequestInput): FormData {
  const form = new FormData();
  const fields: [string, string | undefined][] = [
    ['mode', input.mode],
    ['name', input.name],
    ['phone', input.phone],
    ['email', input.email],
    ['company', input.company],
    ['bin', input.bin],
    ['comment', input.comment],
    ['sku_list', input.skuList],
    ['product_sku', input.productSku],
    ['product_color', input.productColor],
    ['quantity', input.quantity],
    ['page_url', input.pageUrl],
  ];
  for (const [key, value] of fields) {
    const trimmed = value?.trim();
    if (trimmed) form.append(key, trimmed);
  }
  if (input.file) form.append('file', input.file, input.file.name);
  return form;
}

export function submitQuickRequest(
  input: QuickRequestInput,
  idempotencyKey: string,
  { signedIn }: { signedIn: boolean },
): Promise<QuickRequestCreated> {
  const options = {
    method: 'POST' as const,
    body: toQuickRequestForm(input),
    idempotencyKey,
    timeoutMs: UPLOAD_TIMEOUT_MS,
  };
  return signedIn
    ? customerRequest<QuickRequestCreated>('/api/v1/customer/quick-requests', options)
    : apiRequest<QuickRequestCreated>('/api/v1/public/quick-requests', options);
}

/** Проверка файла до отправки — те же правила, что на сервере. */
export function checkAttachment(file: File): string | null {
  const extension = file.name.includes('.') ? file.name.split('.').pop()!.toLowerCase() : '';
  if (!(ATTACHMENT_EXTENSIONS as readonly string[]).includes(extension)) {
    return 'Поддерживаются PDF, Excel, Word, DWG, DXF, CSV, JPG и PNG';
  }
  if (file.size === 0) return 'Файл пуст';
  if (file.size > ATTACHMENT_MAX_MB * 1024 * 1024) {
    return `Файл больше ${ATTACHMENT_MAX_MB} МБ`;
  }
  return null;
}
