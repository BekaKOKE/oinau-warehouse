/**
 * Загрузка файлов — существующий поток медиатеки (товары и CMS):
 *
 *   1. POST /media/upload-intent  → запись PENDING и presigned PUT;
 *   2. PUT файла напрямую в хранилище (R2 / MinIO), минуя API и Next.js;
 *   3. POST /media/{uuid}/complete → проверка объекта, PROCESSING;
 *   4. привязка к товару или ссылка из раздела CMS (PENDING/PROCESSING можно);
 *   5. воркер строит варианты → READY или FAILED (опрос галереи).
 *
 * Файл нигде не сохраняется локально, ключ объекта в интерфейс не попадает:
 * показ идёт только по ссылкам вариантов, которые строит backend.
 */

import { mediaApi, productImagesApi } from '@/lib/api/endpoints';
import type { MediaPurpose, MediaRead, ProductImageList } from '@/lib/api/types';

/** Подсказка для выбора файла; реальную проверку делает backend. */
export const IMAGE_ACCEPT = 'image/jpeg,image/png,image/webp';

export type UploadStage = 'intent' | 'uploading' | 'verifying' | 'attaching' | 'done' | 'error';

export const UPLOAD_STAGE_LABELS: Record<UploadStage, string> = {
  intent: 'Подготовка',
  uploading: 'Загрузка',
  verifying: 'Проверка файла',
  attaching: 'Привязка к товару',
  done: 'Загружено',
  error: 'Ошибка',
};

/** Коды MediaFailureReason backend → понятный текст. */
export const MEDIA_FAILURE_LABELS: Record<string, string> = {
  object_missing: 'Файл не дошёл до хранилища',
  size_exceeded: 'Файл больше допустимого размера',
  empty_file: 'Пустой файл',
  type_mismatch: 'Содержимое не совпадает с типом файла',
  decode_failed: 'Файл не удалось прочитать как изображение',
  too_many_pixels: 'Слишком большое разрешение изображения',
  processing_error: 'Ошибка обработки изображения',
};

export function failureText(reason: string | null | undefined): string {
  return (reason && MEDIA_FAILURE_LABELS[reason]) || 'Файл отклонён';
}

export class StorageUploadError extends Error {
  constructor(readonly status: number) {
    super(
      status === 0
        ? 'Хранилище недоступно: проверьте соединение'
        : `Хранилище отклонило загрузку (${status})`,
    );
    this.name = 'StorageUploadError';
  }
}

/**
 * PUT в хранилище по presigned-ссылке. XMLHttpRequest, а не fetch:
 * только он сообщает прогресс отправки тела.
 */
export function putToStorage(
  url: string,
  method: string,
  headers: Record<string, string>,
  file: Blob,
  onProgress: (percent: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(method, url);
    // Заголовки подписаны вместе со ссылкой — передаются без изменений.
    for (const [name, value] of Object.entries(headers)) xhr.setRequestHeader(name, value);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(new StorageUploadError(xhr.status));
    xhr.onerror = () => reject(new StorageUploadError(0));
    xhr.onabort = () => reject(new DOMException('Загрузка отменена', 'AbortError'));
    signal?.addEventListener('abort', () => xhr.abort());
    xhr.send(file);
  });
}

export type UploadCallbacks = {
  onStage: (stage: UploadStage, percent?: number) => void;
  signal?: AbortSignal;
  /** Подменяется в тестах: jsdom не умеет настоящий PUT. */
  put?: typeof putToStorage;
};

/**
 * Шаги 1–3 для одного файла: ссылка, PUT в хранилище, подтверждение.
 * Возвращает запись медиатеки (обычно PROCESSING) — её UUID и есть ссылка
 * на файл в товаре или разделе CMS.
 */
export async function uploadMediaFile(
  file: File,
  purpose: MediaPurpose,
  { onStage, signal, put = putToStorage }: UploadCallbacks,
): Promise<MediaRead> {
  onStage('intent');
  const created = await mediaApi.uploadIntent(
    { filename: file.name, content_type: file.type, size_bytes: file.size },
    purpose,
  );
  onStage('uploading', 0);
  await put(
    created.upload.url,
    created.upload.method,
    created.upload.headers,
    file,
    (percent) => onStage('uploading', percent),
    signal,
  );
  onStage('verifying');
  return mediaApi.complete(created.media.uuid);
}

/** Полный поток для изображения товара. Возвращает галерею после привязки. */
export async function uploadProductImage(
  productId: number,
  file: File,
  callbacks: UploadCallbacks,
): Promise<ProductImageList> {
  const media = await uploadMediaFile(file, 'PRODUCT', callbacks);
  callbacks.onStage('attaching');
  const gallery = await productImagesApi.attach(productId, media.uuid);
  callbacks.onStage('done');
  return gallery;
}

/** Есть ли в галерее файлы, которые воркер ещё не обработал. */
export function hasPendingImages(gallery: ProductImageList | undefined): boolean {
  return Boolean(
    gallery?.items.some((image) => image.status === 'PENDING' || image.status === 'PROCESSING'),
  );
}

/** Новый порядок после перемещения изображения на позицию `to`. */
export function moveItem<T>(items: readonly T[], from: number, to: number): T[] {
  const next = [...items];
  if (from < 0 || from >= next.length || to < 0 || to >= next.length) return next;
  const [moved] = next.splice(from, 1);
  if (moved !== undefined) next.splice(to, 0, moved);
  return next;
}

// ------------------------------------------------------------ документы

/** Схемы и чертежи (PDF, DWG, DXF): картинки у них нет — показывается тип. */
const DOCUMENT_TYPES: Record<string, string> = {
  'application/pdf': 'PDF',
  'image/vnd.dwg': 'DWG',
  'image/vnd.dxf': 'DXF',
};

export function documentType(contentType: string | null | undefined): string | null {
  return (contentType && DOCUMENT_TYPES[contentType]) || null;
}

/** Роль файла в карточке товара. */
export const IMAGE_KIND_LABELS: Record<string, string> = {
  PHOTO: 'Фото',
  SCHEME: 'Схема',
  DRAWING: 'Чертёж',
  CERTIFICATE: 'Сертификат',
};
