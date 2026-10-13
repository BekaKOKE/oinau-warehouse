/**
 * Массовый импорт (ZIP): вкладка раздела, шаблон и пример, загрузка
 * архива в хранилище, проверка воркером, предпросмотр, применение,
 * отчёт, отмена и права.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AppProviders } from '@/components/AppProviders';
import { BundleWizard } from '@/components/imports/BundleWizard';
import { ImportExportScreen } from '@/components/imports/ImportExportScreen';
import { AuthGate } from '@/components/session/AuthGate';
import type { BundleJob, ImportJobStatus, UserRole } from '@/lib/api/types';
import { resetSessionForTests } from '@/lib/auth/session';
import { bundleFigures, bundleStep, checkZipFile } from '@/lib/bundle';

import { HISTORY_URL, makeIssue } from './import-fixtures';
import { createFetchMock, fileResponse, jsonResponse, page, signInAs } from './helpers';
import { navigationState, routerReplace } from './setup';

const BUNDLES = '/api/v1/admin/catalog/bundle-imports';
const UUID = '0b8f7a4c-1d2e-4f3a-9b8c-7d6e5f4a3b2c';
const JOB = `${BUNDLES}/${UUID}`;

let net: ReturnType<typeof createFetchMock>;
let saved: string[];

function makeBundleJob(status: ImportJobStatus, overrides: Partial<BundleJob> = {}): BundleJob {
  return {
    uuid: UUID,
    kind: 'catalog_bundle',
    status,
    filename: 'catalog.zip',
    file_size: 4096,
    file_sha256: 'a'.repeat(64),
    rows_total: 152,
    products_created: 120,
    products_updated: 32,
    products_unchanged: 0,
    error_count: 0,
    warning_count: 0,
    failure_code: null,
    created_by_id: 1,
    committed_by_id: null,
    created_at: '2026-09-30T08:00:00Z',
    committed_at: null,
    expires_at: '2026-10-01T08:00:00Z',
    can_commit: status === 'VALID',
    summary: { rows_total: 152 },
    bundle: {
      photos: { total: 438, added: 438, removed: 0, uploaded: 400, reused: 38 },
      schemes: { total: 146, added: 146, removed: 0, uploaded: 146, reused: 0 },
      stock_updated: 150,
      files_in_archive: 584,
      files_unused: 0,
    },
    errors: [],
    warnings: [],
    changes: [
      { row: 2, sku: '504-176', action: 'create', changed: [] },
      { row: 3, sku: 'KAN-16', action: 'update', changed: ['pricing', 'photos', 'stock'] },
    ],
    changes_truncated: false,
    can_cancel: ['UPLOADING', 'CHECKING', 'VALID', 'INVALID'].includes(status),
    ...overrides,
  };
}

function zipFile(name = 'catalog.zip', size = 4096): File {
  return new File([new Uint8Array(size)], name, { type: 'application/zip' });
}

/** Ответы GET задачи по очереди: последний повторяется. */
function onJob(...jobs: BundleJob[]) {
  const queue = [...jobs];
  net.on('GET', JOB, () => jsonResponse(queue.length > 1 ? queue.shift() : queue[0]));
}

function renderWizard(role: UserRole = 'CONTENT_MANAGER') {
  signInAs(net, role);
  const put = vi.fn(
    async (
      _url: string,
      _method: string,
      _headers: Record<string, string>,
      _file: Blob,
      onProgress: (percent: number) => void,
    ) => {
      onProgress(50);
      onProgress(100);
    },
  );
  const onCommitted = vi.fn();
  render(
    <AppProviders>
      <AuthGate>
        <BundleWizard onCommitted={onCommitted} put={put} pollMs={5} />
      </AuthGate>
    </AppProviders>,
  );
  return { put, onCommitted };
}

async function uploadArchive(user: ReturnType<typeof userEvent.setup>) {
  net.on('POST', BUNDLES, {
    job: makeBundleJob('UPLOADING'),
    upload: {
      url: 'https://storage.test/bucket/imports/x/bundle.zip?sig=1',
      method: 'PUT',
      headers: { 'Content-Type': 'application/zip' },
      expires_in: 600,
    },
  });
  net.on('POST', `${JOB}/check`, makeBundleJob('CHECKING'));
  await user.upload(await screen.findByLabelText('ZIP-архив с каталогом'), zipFile());
  await user.click(screen.getByRole('button', { name: 'Загрузить и проверить' }));
}

beforeEach(() => {
  resetSessionForTests();
  net = createFetchMock();
  vi.stubGlobal('fetch', net.mock);
  saved = [];
  vi.stubGlobal(
    'URL',
    Object.assign(URL, { createObjectURL: () => 'blob:x', revokeObjectURL: () => {} }),
  );
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    saved.push(this.download);
  });
  navigationState.search = '';
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// ================================================================= вкладки
describe('раздел «Импорт / экспорт»', () => {
  function renderScreen(ui: ReactNode) {
    return render(
      <AppProviders>
        <AuthGate>{ui}</AuthGate>
      </AppProviders>,
    );
  }

  it('обычный Excel-импорт остаётся, ZIP — отдельной вкладкой в адресе', async () => {
    const user = userEvent.setup();
    signInAs(net, 'CONTENT_MANAGER');
    navigationState.pathname = '/import-export';
    net.on('GET', HISTORY_URL, page([]));
    renderScreen(<ImportExportScreen />);

    const tabs = await screen.findByRole('tablist', { name: 'Способ импорта' });
    expect(within(tabs).getByRole('tab', { name: 'Импорт Excel' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(screen.getByRole('button', { name: 'Скачать каталог (XLSX)' })).toBeInTheDocument();

    await user.click(within(tabs).getByRole('tab', { name: 'Массовый импорт (ZIP)' }));
    expect(routerReplace).toHaveBeenCalledWith('/import-export?tab=bundle', { scroll: false });
  });

  it('?tab=bundle открывает мастер ZIP', async () => {
    signInAs(net, 'CONTENT_MANAGER');
    navigationState.pathname = '/import-export';
    navigationState.search = 'tab=bundle';
    renderScreen(<ImportExportScreen />);
    expect(
      await screen.findByRole('heading', { name: 'Массовый импорт товаров' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Загрузить ZIP' })).toBeInTheDocument();
  });
});

// ============================================================ шаг 1 — файл
describe('шаг 1 — файл', () => {
  it('шаблон Excel и пример ZIP скачиваются', async () => {
    const user = userEvent.setup();
    renderWizard();
    net.on('GET', `${BUNDLES}/template`, fileResponse('PK', 'products.xlsx'));
    net.on('GET', `${BUNDLES}/example`, fileResponse('PK', 'oinau-import-example.zip'));

    await user.click(await screen.findByRole('button', { name: 'Скачать шаблон Excel' }));
    await user.click(screen.getByRole('button', { name: 'Скачать пример ZIP' }));
    await waitFor(() => expect(saved).toEqual(['products.xlsx', 'oinau-import-example.zip']));
  });

  it('не ZIP не отправляется', async () => {
    const user = userEvent.setup({ applyAccept: false });
    renderWizard();
    await user.upload(
      await screen.findByLabelText('ZIP-архив с каталогом'),
      zipFile('catalog.rar'),
    );
    expect(await screen.findByRole('alert')).toHaveTextContent('Нужен ZIP-архив');
    expect(screen.queryByRole('button', { name: 'Загрузить и проверить' })).toBeNull();
    expect(net.calls('POST', BUNDLES)).toHaveLength(0);
  });

  it('без прав записи загрузки нет', async () => {
    renderWizard('VIEWER');
    expect(
      await screen.findByText(/Загружать архивы может сотрудник с правом изменения каталога/),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText('ZIP-архив с каталогом')).toBeNull();
  });
});

// ======================================================= полный сценарий
describe('проверка → предпросмотр → импорт → отчёт', () => {
  it('архив уходит в хранилище, импорт применяется только по кнопке', async () => {
    const user = userEvent.setup();
    const { put, onCommitted } = renderWizard();
    onJob(makeBundleJob('CHECKING'), makeBundleJob('VALID'));
    await uploadArchive(user);

    // Шаг 2 — проверка воркером, затем предпросмотр
    expect(
      await screen.findByRole('heading', { name: 'Предпросмотр импорта' }),
    ).toBeInTheDocument();
    expect(put).toHaveBeenCalledTimes(1);
    expect(put.mock.calls[0]?.[0]).toBe('https://storage.test/bucket/imports/x/bundle.zip?sig=1');
    expect(JSON.parse(String(net.calls('POST', BUNDLES)[0]?.[1]?.body))).toEqual({
      filename: 'catalog.zip',
      size_bytes: 4096,
    });

    const figures = Object.fromEntries(
      Array.from(document.querySelectorAll('dl div')).map((item) => [
        item.querySelector('dt')?.textContent,
        item.querySelector('dd')?.textContent?.replace(/\s/g, ''),
      ]),
    );
    expect(figures).toMatchObject({
      'Найдено товаров': '152',
      Новых: '120',
      'Будут обновлены': '32',
      Фотографий: '438',
      Схем: '146',
      Ошибок: '0',
    });
    expect(screen.getByText('цены, фото, остаток')).toBeInTheDocument();
    // Каталог не меняется, пока не нажато «Применить»
    expect(net.calls('POST', `${JOB}/commit`)).toHaveLength(0);

    net.on('POST', `${JOB}/commit`, makeBundleJob('APPLYING'));
    onJob(
      makeBundleJob('APPLYING'),
      makeBundleJob('COMMITTED', { committed_at: '2026-09-30T08:05:00Z' }),
    );
    await user.click(screen.getByRole('button', { name: 'Применить импорт' }));
    const dialog = await screen.findByRole('dialog', { name: 'Применить импорт?' });
    await user.click(within(dialog).getByRole('button', { name: 'Применить' }));

    expect(await screen.findByRole('heading', { name: 'Импорт завершён' })).toBeInTheDocument();
    expect(screen.getByText('Фото добавлено')).toBeInTheDocument();
    expect(onCommitted).toHaveBeenCalledTimes(1);

    net.on('GET', `${JOB}/report`, fileResponse('PK', 'oinau-import-report.xlsx'));
    await user.click(screen.getByRole('button', { name: 'Скачать отчёт' }));
    await waitFor(() => expect(saved).toEqual(['oinau-import-report.xlsx']));

    await user.click(screen.getByRole('button', { name: 'Импортировать ещё' }));
    expect(
      await screen.findByRole('heading', { name: 'Массовый импорт товаров' }),
    ).toBeInTheDocument();
  });

  it('ошибки проверки: список с артикулом и строкой, применить нельзя, отмена удаляет', async () => {
    const user = userEvent.setup();
    renderWizard();
    const invalid = makeBundleJob('INVALID', {
      error_count: 2,
      errors: [
        makeIssue({
          sheet: 'Товары',
          row: 27,
          column: 'Фото',
          code: 'file_not_found',
          message: 'Артикул 504-999: не найден файл photos/504-999.jpg',
        }),
        makeIssue({
          sheet: 'Товары',
          row: 48,
          column: 'Категория',
          code: 'category_not_found',
          message: 'Категория «Комплектующие для чего-то» не существует',
        }),
      ],
    });
    onJob(invalid);
    await uploadArchive(user);

    expect(await screen.findByText('Импорт применить нельзя.')).toBeInTheDocument();
    expect(
      screen.getByText('Артикул 504-999: не найден файл photos/504-999.jpg'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Категория «Комплектующие для чего-то» не существует'),
    ).toBeInTheDocument();
    expect(screen.getByText('Товары, строка 27, колонка Фото')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Применить импорт' })).toBeDisabled();

    net.on('DELETE', JOB, makeBundleJob('CANCELLED'));
    await user.click(screen.getByRole('button', { name: 'Отменить импорт' }));
    const dialog = await screen.findByRole('dialog', { name: 'Отменить импорт?' });
    await user.click(within(dialog).getByRole('button', { name: 'Отменить импорт' }));
    expect(
      await screen.findByRole('heading', { name: 'Массовый импорт товаров' }),
    ).toBeInTheDocument();
    expect(net.calls('DELETE', JOB)).toHaveLength(1);
  });

  it('неудачное применение показывает причину и отчёт', async () => {
    const user = userEvent.setup();
    renderWizard();
    onJob(makeBundleJob('VALID'));
    await uploadArchive(user);
    await screen.findByRole('heading', { name: 'Предпросмотр импорта' });

    net.on('POST', `${JOB}/commit`, makeBundleJob('APPLYING'));
    onJob(
      makeBundleJob('FAILED', {
        failure_code: 'import_validation_failed',
        error_count: 1,
        errors: [makeIssue({ code: 'slug_taken', message: 'slug уже занят' })],
      }),
    );
    await user.click(screen.getByRole('button', { name: 'Применить импорт' }));
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: 'Применить' }),
    );
    expect(await screen.findByRole('heading', { name: 'Импорт не применён' })).toBeInTheDocument();
    expect(screen.getByText('Каталог изменился после предпросмотра.')).toBeInTheDocument();
    expect(screen.getByText('slug уже занят')).toBeInTheDocument();
  });
});

// ============================================================== логика
describe('lib/bundle', () => {
  it('проверка файла до загрузки', () => {
    expect(checkZipFile(zipFile())).toBeNull();
    expect(checkZipFile(zipFile('catalog.xlsx'))).toMatch(/ZIP/);
    expect(checkZipFile(zipFile('empty.zip', 0))).toBe('Файл пуст.');
  });

  it('шаг мастера по статусу', () => {
    expect(bundleStep(null)).toBe(0);
    expect(bundleStep('CHECKING')).toBe(1);
    expect(bundleStep('INVALID')).toBe(2);
    expect(bundleStep('APPLYING')).toBe(3);
    expect(bundleStep('COMMITTED')).toBe(4);
  });

  it('после применения — фактические цифры', () => {
    const figures = bundleFigures(makeBundleJob('COMMITTED', { error_count: 3 }));
    expect(figures.find((item) => item.key === 'create')?.label).toBe('Создано');
    expect(figures.find((item) => item.key === 'errors')).toMatchObject({
      value: 3,
      tone: 'danger',
    });
  });
});
