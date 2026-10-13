/**
 * Импорт и экспорт каталога: подписи, проверка файла, фильтры истории.
 *
 * Правил импорта здесь нет. Формат книги, состав проверок и план
 * изменений считает backend (этап 5E) — экран показывает его отчёт.
 * Фронтенд проверяет только то, что backend всё равно отвергнет
 * (расширение, пустой файл, размер), чтобы не гонять мегабайты впустую.
 */

import { ApiError } from '@/lib/api/client';
import type {
  ImportEntityCounts,
  ImportIssue,
  ImportJobStatus,
  ImportSummary,
} from '@/lib/api/types';
import { IMPORT_STATUS } from '@/lib/labels';

// ------------------------------------------------------------- файл

/** Подсказка для диалога выбора файла; настоящая проверка — на backend. */
export const XLSX_ACCEPT = '.xlsx';

/**
 * Совпадает с UPLOAD_MAX_SIZE_MB backend. Значение продублировано,
 * потому что наружу оно не отдаётся; при расхождении сервер ответит
 * 413, и это сообщение покажется пользователю как есть.
 */
export const MAX_FILE_SIZE_MB = 15;

export function checkXlsxFile(file: File): string | null {
  if (!file.name.toLowerCase().endsWith('.xlsx')) {
    return 'Нужна книга Excel в формате .xlsx. Форматы .xls, .xlsm и CSV не принимаются.';
  }
  if (file.size === 0) return 'Файл пуст.';
  if (file.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
    return `Файл больше ${MAX_FILE_SIZE_MB} МБ.`;
  }
  return null;
}

// ---------------------------------------------------------- подписи

/** Почему импорт нельзя подтвердить. Коды — из ошибок backend. */
const IMPORT_FAILURE_LABELS: Record<string, string> = {
  import_not_valid: 'Предпросмотр нашёл ошибки в файле',
  import_already_committed: 'Импорт уже применён',
  import_failed: 'Подтверждение было отклонено',
  import_preview_expired: 'Предпросмотр устарел',
  import_file_mismatch: 'Файл отличается от проверенного',
  import_validation_failed: 'Каталог изменился после предпросмотра',
  integrity_error: 'Конфликт с текущими данными каталога',
  internal_error: 'Внутренняя ошибка при применении',
  import_bundle_state: 'Импорт уже не в том состоянии',
  timeout: 'Обработка не завершилась вовремя',
};

export function failureText(code: string | null | undefined): string | null {
  if (!code) return null;
  return IMPORT_FAILURE_LABELS[code] ?? 'Импорт не применён';
}

/** Что именно меняется у товара (ProductChangeRead.changed). */
const CHANGE_PART_LABELS: Record<string, string> = {
  slug: 'адрес',
  status: 'статус',
  is_active: 'активность',
  is_featured: 'рекомендуемый',
  unit: 'единица',
  brand: 'бренд',
  external_id: 'код 1С',
  min_order_qty: 'минимальный заказ',
  translations: 'тексты',
  categories: 'категории',
  attributes: 'характеристики',
  specs: 'характеристики (текст)',
  pricing: 'цены',
  photos: 'фото',
  schemes: 'схемы',
  stock: 'остаток',
};

export function changePartLabel(part: string): string {
  return CHANGE_PART_LABELS[part] ?? part;
}

export type ImportEntityKey = 'products' | 'categories' | 'attributes' | 'attribute_options';

const ENTITY_LABELS: { key: ImportEntityKey; label: string }[] = [
  { key: 'products', label: 'Товары' },
  { key: 'categories', label: 'Категории' },
  { key: 'attributes', label: 'Характеристики' },
  { key: 'attribute_options', label: 'Варианты значений' },
];

export type SummaryRow = { key: ImportEntityKey; label: string } & ImportEntityCounts;

/** Сводка по сущностям в порядке показа; пустые строки не скрываются. */
export function summaryRows(summary: ImportSummary | undefined): SummaryRow[] {
  if (!summary) return [];
  return ENTITY_LABELS.map(({ key, label }) => {
    const counts: ImportEntityCounts | undefined = summary[key];
    return {
      key,
      label,
      create: counts?.create ?? 0,
      update: counts?.update ?? 0,
      unchanged: counts?.unchanged ?? 0,
    };
  });
}

/** Будут ли вообще изменения, если подтвердить импорт. */
export function hasChanges(summary: ImportSummary | undefined): boolean {
  return summaryRows(summary).some((row) => row.create > 0 || row.update > 0);
}

export function totalChanges(summary: ImportSummary | undefined): number {
  return summaryRows(summary).reduce((sum, row) => sum + row.create + row.update, 0);
}

/** Место ошибки: «Products, строка 12, колонка sku». */
export function issueLocation(issue: ImportIssue): string {
  const parts: string[] = [];
  if (issue.sheet) parts.push(issue.sheet);
  if (issue.row !== null && issue.row !== undefined) parts.push(`строка ${issue.row}`);
  if (issue.column) parts.push(`колонка ${issue.column}`);
  return parts.length > 0 ? parts.join(', ') : 'Книга целиком';
}

/** Ключ строки отчёта: одинаковых сочетаний лист/строка/колонка/код не бывает. */
export function issueKey(issue: ImportIssue, index: number): string {
  return `${issue.sheet ?? ''}:${issue.row ?? ''}:${issue.column ?? ''}:${issue.code}:${index}`;
}

// --------------------------------------------------------- отказ загрузки

/**
 * Отказ принять файл целиком (413/415/422) — в отличие от ошибок
 * в данных, которые приходят списком в отчёте предпросмотра.
 */
export function uploadErrorText(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null;
  const known: Record<string, string> = {
    import_unsupported_file: 'Поддерживается только книга Excel .xlsx',
    import_file_corrupted: 'Файл повреждён или не является книгой Excel',
    import_file_empty: 'Файл пуст',
    import_file_missing: 'Файл не передан',
    import_file_too_large: `Файл больше ${MAX_FILE_SIZE_MB} МБ`,
    import_upload_invalid: 'Файл не удалось прочитать. Попробуйте ещё раз',
  };
  return known[error.code] ?? null;
}

/**
 * Ошибки повторной проверки при подтверждении (422
 * import_validation_failed): backend кладёт их в details.errors.
 */
export function issuesFromError(error: unknown): ImportIssue[] {
  if (!(error instanceof ApiError)) return [];
  const raw = error.details?.errors;
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (item): item is ImportIssue =>
      typeof item === 'object' && item !== null && 'code' in item && 'message' in item,
  );
}

// ------------------------------------------------------- фильтры истории

export type ImportFilters = { search: string; status: ImportJobStatus | ''; page: number };

export function parseImportFilters(params: URLSearchParams): ImportFilters {
  const status = params.get('status') ?? '';
  const page = Number.parseInt(params.get('page') ?? '', 10);
  return {
    // Поиска по истории backend не поддерживает — поле не показывается,
    // но useUrlFilters требует его в форме фильтров.
    search: '',
    status: status in IMPORT_STATUS ? (status as ImportJobStatus) : '',
    page: Number.isFinite(page) && page > 0 ? page : 1,
  };
}

export function serializeImportFilters(filters: ImportFilters): string {
  const params = new URLSearchParams();
  if (filters.status) params.set('status', filters.status);
  if (filters.page > 1) params.set('page', String(filters.page));
  const query = params.toString();
  return query ? `?${query}` : '';
}

export function importListQuery(filters: ImportFilters, pageSize: number) {
  return {
    status: filters.status || undefined,
    page: filters.page,
    page_size: pageSize,
  };
}
