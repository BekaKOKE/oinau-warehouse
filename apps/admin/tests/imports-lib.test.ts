/**
 * Импорт/экспорт: чистые функции — проверка файла, сводка, фильтры,
 * разбор ошибок backend и имя файла из Content-Disposition.
 */

import { describe, expect, it } from 'vitest';

import { ApiError, filenameFromResponse } from '@/lib/api/client';
import {
  changePartLabel,
  checkXlsxFile,
  failureText,
  hasChanges,
  importListQuery,
  issueLocation,
  issuesFromError,
  parseImportFilters,
  serializeImportFilters,
  summaryRows,
  totalChanges,
  uploadErrorText,
} from '@/lib/imports';

import { makeIssue, makeSummary } from './import-fixtures';
import { fileResponse, xlsxFile } from './helpers';

describe('проверка файла до отправки', () => {
  it('принимает .xlsx', () => {
    expect(checkXlsxFile(xlsxFile())).toBeNull();
    expect(checkXlsxFile(xlsxFile('КАТАЛОГ.XLSX'))).toBeNull();
  });

  it('отвергает другие форматы, пустой и слишком большой файл', () => {
    expect(checkXlsxFile(xlsxFile('catalog.csv'))).toMatch(/\.xlsx/);
    expect(checkXlsxFile(xlsxFile('catalog.xls'))).toMatch(/\.xlsx/);
    expect(checkXlsxFile(xlsxFile('catalog.xlsx', 0))).toMatch(/пуст/);
    expect(checkXlsxFile(xlsxFile('catalog.xlsx', 16 * 1024 * 1024))).toMatch(/15 МБ/);
  });
});

describe('сводка предпросмотра', () => {
  it('раскладывает счётчики по сущностям в фиксированном порядке', () => {
    const rows = summaryRows(makeSummary());
    expect(rows.map((row) => row.key)).toEqual([
      'products',
      'categories',
      'attributes',
      'attribute_options',
    ]);
    expect(rows[0]).toMatchObject({ create: 2, update: 1, unchanged: 5 });
  });

  it('считает, есть ли что применять', () => {
    expect(hasChanges(makeSummary())).toBe(true);
    expect(totalChanges(makeSummary())).toBe(5);

    const nothing = makeSummary({
      products: { create: 0, update: 0, unchanged: 9 },
      categories: { create: 0, update: 0, unchanged: 2 },
      attributes: { create: 0, update: 0, unchanged: 0 },
      attribute_options: { create: 0, update: 0, unchanged: 0 },
    });
    expect(hasChanges(nothing)).toBe(false);
    expect(totalChanges(nothing)).toBe(0);
  });

  it('пустая сводка не ломает экран', () => {
    expect(summaryRows(undefined)).toEqual([]);
    expect(hasChanges(undefined)).toBe(false);
  });
});

describe('подписи', () => {
  it('место ошибки читается человеком', () => {
    expect(issueLocation(makeIssue())).toBe('Products, строка 12, колонка sku');
    expect(issueLocation(makeIssue({ row: null, column: null }))).toBe('Products');
    expect(issueLocation(makeIssue({ sheet: null, row: null, column: null }))).toBe(
      'Книга целиком',
    );
  });

  it('причина отказа и части изменений', () => {
    expect(failureText('import_preview_expired')).toMatch(/устарел/);
    expect(failureText('whatever')).toBe('Импорт не применён');
    expect(failureText(null)).toBeNull();
    expect(changePartLabel('pricing')).toBe('цены');
    expect(changePartLabel('unknown_part')).toBe('unknown_part');
  });

  it('отказ принять файл переводится в текст, прочие ошибки — нет', () => {
    const rejected = new ApiError(415, 'import_unsupported_file', 'Только .xlsx');
    expect(uploadErrorText(rejected)).toMatch(/xlsx/);
    expect(uploadErrorText(new ApiError(500, 'internal', 'x'))).toBeNull();
    expect(uploadErrorText(new Error('network'))).toBeNull();
  });
});

describe('ошибки повторной проверки при подтверждении', () => {
  it('достаются из details.errors', () => {
    const error = new ApiError(422, 'import_validation_failed', 'Каталог изменился', {
      error_count: 1,
      errors: [{ sheet: 'Products', row: 2, column: 'slug', code: 'slug_taken', message: 'Занят' }],
    });
    expect(issuesFromError(error)).toHaveLength(1);
    expect(issuesFromError(new ApiError(409, 'conflict', 'x'))).toEqual([]);
    expect(issuesFromError(new Error('x'))).toEqual([]);
  });
});

describe('фильтры истории', () => {
  it('читаются из адреса и пишутся обратно', () => {
    const filters = parseImportFilters(new URLSearchParams('status=COMMITTED&page=3'));
    expect(filters).toEqual({ search: '', status: 'COMMITTED', page: 3 });
    expect(serializeImportFilters(filters)).toBe('?status=COMMITTED&page=3');
  });

  it('неизвестный статус и страница игнорируются', () => {
    expect(parseImportFilters(new URLSearchParams('status=WAT&page=-2'))).toEqual({
      search: '',
      status: '',
      page: 1,
    });
    expect(serializeImportFilters({ search: '', status: '', page: 1 })).toBe('');
  });

  it('пустой фильтр не уходит в запрос', () => {
    expect(importListQuery({ search: '', status: '', page: 2 }, 10)).toEqual({
      status: undefined,
      page: 2,
      page_size: 10,
    });
  });
});

describe('имя файла из ответа', () => {
  it('берётся из Content-Disposition', () => {
    expect(filenameFromResponse(fileResponse('x', 'oinau-catalog-2026-09-17.xlsx'))).toBe(
      'oinau-catalog-2026-09-17.xlsx',
    );
  });

  it('без заголовка — null', () => {
    expect(filenameFromResponse(fileResponse('x'))).toBeNull();
  });
});
