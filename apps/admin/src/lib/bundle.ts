/**
 * Массовый импорт (ZIP): проверка файла до загрузки, этапы, сводка.
 *
 * Правил импорта здесь нет — архив и книгу проверяет backend.
 * Фронтенд отсекает только то, что сервер всё равно отвергнет
 * (не .zip, пустой файл, больше лимита), чтобы не гнать мегабайты зря.
 */

import type { BundleJob, ImportJobStatus } from '@/lib/api/types';

export const ZIP_ACCEPT = '.zip,application/zip';

/** Совпадает с IMPORT_BUNDLE_MAX_MB backend; сервер проверит сам. */
export const MAX_BUNDLE_SIZE_MB = 1024;

/** Как часто опрашивать задачу, пока воркер проверяет или применяет архив. */
export const POLL_INTERVAL_MS = 1500;

export function checkZipFile(file: File): string | null {
  if (!file.name.toLowerCase().endsWith('.zip')) {
    return 'Нужен ZIP-архив: products.xlsx и папки photos/ и schemes/.';
  }
  if (file.size === 0) return 'Файл пуст.';
  if (file.size > MAX_BUNDLE_SIZE_MB * 1024 * 1024) {
    return `Архив больше ${MAX_BUNDLE_SIZE_MB} МБ — разбейте его на части.`;
  }
  return null;
}

/** Статусы, пока которые экран опрашивает сервер. */
const WORKING: ReadonlySet<ImportJobStatus> = new Set(['UPLOADING', 'CHECKING', 'APPLYING']);

export function isWorking(status: ImportJobStatus): boolean {
  return WORKING.has(status);
}

export const BUNDLE_STEPS = ['Файл', 'Проверка', 'Предпросмотр', 'Импорт', 'Отчёт'] as const;

/** Номер шага мастера по статусу задачи. */
export function bundleStep(status: ImportJobStatus | null): number {
  switch (status) {
    case null:
      return 0;
    case 'UPLOADING':
    case 'CHECKING':
      return 1;
    case 'VALID':
    case 'INVALID':
      return 2;
    case 'APPLYING':
      return 3;
    default:
      return 4;
  }
}

export type BundleFigure = {
  key: string;
  label: string;
  value: number;
  tone?: 'danger' | 'warning';
};

/**
 * Итог в цифрах: «Найдено 152 товара, новых 120, будут обновлены 32,
 * фото 438, схем 146, ошибок 3». После применения — факт.
 */
export function bundleFigures(job: BundleJob): BundleFigure[] {
  const applied = job.status === 'COMMITTED';
  const photos = job.bundle.photos ?? { total: 0, added: 0, uploaded: 0 };
  const schemes = job.bundle.schemes ?? { total: 0, added: 0, uploaded: 0 };
  const found = job.products_created + job.products_updated + job.products_unchanged;
  return [
    { key: 'found', label: 'Найдено товаров', value: found },
    { key: 'create', label: applied ? 'Создано' : 'Новых', value: job.products_created },
    {
      key: 'update',
      label: applied ? 'Обновлено' : 'Будут обновлены',
      value: job.products_updated,
    },
    {
      key: 'photos',
      label: applied ? 'Фото добавлено' : 'Фотографий',
      value: applied ? (photos.added ?? 0) : (photos.total ?? 0),
    },
    {
      key: 'schemes',
      label: applied ? 'Схем добавлено' : 'Схем',
      value: applied ? (schemes.added ?? 0) : (schemes.total ?? 0),
    },
    { key: 'stock', label: 'Остатков', value: job.bundle.stock_updated ?? 0 },
    {
      key: 'errors',
      label: 'Ошибок',
      value: job.error_count,
      tone: job.error_count > 0 ? 'danger' : undefined,
    },
    {
      key: 'warnings',
      label: 'Предупреждений',
      value: job.warning_count,
      tone: job.warning_count > 0 ? 'warning' : undefined,
    },
  ];
}
