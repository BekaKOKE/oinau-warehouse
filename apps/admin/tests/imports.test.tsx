/**
 * Раздел «Импорт / экспорт»: выгрузка XLSX, три шага импорта
 * (файл → проверка → применение), история и права.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AppProviders } from '@/components/AppProviders';
import { ImportExportScreen } from '@/components/imports/ImportExportScreen';
import { AuthGate } from '@/components/session/AuthGate';
import type { ImportPreview, UserRole } from '@/lib/api/types';
import { resetSessionForTests } from '@/lib/auth/session';

import {
  COMMIT_URL,
  EXPORT_URL,
  HISTORY_URL,
  invalidPreview,
  JOB_URL,
  makeCommit,
  makeJob,
  makeJobDetail,
  makeIssue,
  makePreview,
  PREVIEW_URL,
  TEMPLATE_URL,
} from './import-fixtures';
import {
  createFetchMock,
  errorResponse,
  fileResponse,
  jsonResponse,
  makeUser,
  page,
  signInAs,
  tokens,
  xlsxFile,
} from './helpers';
import { navigationState, routerReplace } from './setup';

let net: ReturnType<typeof createFetchMock>;
let clicked: string[];

function renderInPanel(ui: ReactNode) {
  return render(
    <AppProviders>
      <AuthGate>{ui}</AuthGate>
    </AppProviders>,
  );
}

async function openScreen(role: UserRole = 'CONTENT_MANAGER', jobs = [makeJob()]) {
  signInAs(net, role);
  navigationState.pathname = '/import-export';
  net.on('GET', HISTORY_URL, page(jobs, jobs.length));
  renderInPanel(<ImportExportScreen />);
  return screen.findByRole('heading', { name: 'Импорт / экспорт' });
}

/** Выбор файла через скрытый input: drag&drop в jsdom не воспроизводится. */
async function chooseFile(user: ReturnType<typeof userEvent.setup>, name = 'new-prices.xlsx') {
  const input = screen.getByLabelText('Файл каталога в формате XLSX');
  await user.upload(input, xlsxFile(name));
}

async function reachPreview(
  user: ReturnType<typeof userEvent.setup>,
  preview: ImportPreview = makePreview(),
) {
  net.on('POST', PREVIEW_URL, jsonResponse(preview));
  await chooseFile(user);
  await user.click(await screen.findByRole('button', { name: 'Проверить файл' }));
  return screen.findByRole('heading', { name: 'Проверка файла' });
}

beforeEach(() => {
  resetSessionForTests();
  net = createFetchMock();
  vi.stubGlobal('fetch', net.mock);
  clicked = [];
  // jsdom не умеет ни object URL, ни настоящее скачивание.
  vi.stubGlobal(
    'URL',
    Object.assign(URL, { createObjectURL: () => 'blob:x', revokeObjectURL: () => {} }),
  );
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    clicked.push(this.download);
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('экспорт', () => {
  it('скачивает каталог под именем из ответа backend', async () => {
    const user = userEvent.setup();
    await openScreen();
    net.on('GET', EXPORT_URL, fileResponse('PK', 'oinau-catalog-2026-09-17.xlsx'));

    await user.click(screen.getByRole('button', { name: 'Скачать каталог (XLSX)' }));

    await waitFor(() => expect(clicked).toEqual(['oinau-catalog-2026-09-17.xlsx']));
    const [call] = net.calls('GET', EXPORT_URL);
    expect((call?.[1] as RequestInit).headers).toMatchObject({ Authorization: 'Bearer access' });
    expect(await screen.findByText('Файл готов')).toBeInTheDocument();
  });

  it('шаблон скачивается отдельной кнопкой', async () => {
    const user = userEvent.setup();
    await openScreen();
    net.on('GET', TEMPLATE_URL, fileResponse('PK'));

    await user.click(screen.getByRole('button', { name: 'Пустой шаблон' }));

    await waitFor(() => expect(clicked).toEqual(['oinau-catalog-template.xlsx']));
  });

  it('ошибка сервера показывается тостом, файл не сохраняется', async () => {
    const user = userEvent.setup();
    await openScreen();
    net.on('GET', EXPORT_URL, errorResponse(500, 'internal_error', 'Ошибка сервера'));

    await user.click(screen.getByRole('button', { name: 'Скачать каталог (XLSX)' }));

    expect(await screen.findByText('Не удалось выгрузить файл')).toBeInTheDocument();
    expect(clicked).toEqual([]);
  });
});

describe('шаг 1 — файл', () => {
  it('не отправляет файл неподдерживаемого формата', async () => {
    // applyAccept: false — иначе user-event отсеет «не тот» файл сам
    // (как диалог браузера), и проверка расширения осталась бы непроверенной.
    const user = userEvent.setup({ applyAccept: false });
    await openScreen();

    await chooseFile(user, 'catalog.csv');

    expect(await screen.findByRole('alert')).toHaveTextContent(/\.xlsx/);
    expect(screen.queryByRole('button', { name: 'Проверить файл' })).not.toBeInTheDocument();
    expect(net.calls('POST', PREVIEW_URL)).toHaveLength(0);
  });

  it('выбранный файл показывается с размером и снимается кнопкой «Убрать»', async () => {
    const user = userEvent.setup();
    await openScreen();

    await chooseFile(user);

    const meta = (await screen.findByText('new-prices.xlsx')).parentElement as HTMLElement;
    expect(within(meta).getByText('2 КБ')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Убрать' }));
    expect(screen.getByRole('button', { name: 'Выбрать файл' })).toBeInTheDocument();
  });

  it('отказ backend принять книгу объясняется человеку', async () => {
    const user = userEvent.setup();
    await openScreen();
    net.on(
      'POST',
      PREVIEW_URL,
      errorResponse(415, 'import_unsupported_file', 'Поддерживается только .xlsx'),
    );

    await chooseFile(user);
    await user.click(await screen.findByRole('button', { name: 'Проверить файл' }));

    const toast = await screen.findByRole('alert');
    expect(toast).toHaveTextContent('Файл не принят');
    expect(toast).toHaveTextContent('Поддерживается только книга Excel .xlsx');
  });
});

describe('шаг 2 — проверка', () => {
  it('файл без ошибок: сводка и доступное применение', async () => {
    const user = userEvent.setup();
    await openScreen();
    await reachPreview(user);

    const [call] = net.calls('POST', PREVIEW_URL);
    expect((call?.[1] as RequestInit).body).toBeInstanceOf(FormData);
    expect(screen.getByText(/Ошибок нет\./)).toBeInTheDocument();
    const products = screen.getByText('Товары').closest('div') as HTMLElement;
    expect(within(products).getByText(/создать/)).toHaveTextContent('2');
    expect(within(products).getByText(/изменить/)).toHaveTextContent('1');
    expect(screen.getByRole('button', { name: 'Применить импорт' })).toBeEnabled();
    // Что именно изменится у товара
    expect(screen.getByText('цены, категории')).toBeInTheDocument();
    expect(screen.getByText('новый товар')).toBeInTheDocument();
  });

  it('ошибки в данных блокируют применение и перечислены по строкам', async () => {
    const user = userEvent.setup();
    await openScreen();
    await reachPreview(user, invalidPreview());

    expect(screen.getByText(/Импорт применить нельзя\./)).toBeInTheDocument();
    expect(screen.getByText('Products, строка 12, колонка sku')).toBeInTheDocument();
    expect(screen.getByText('Цена должна быть больше нуля')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Применить импорт' })).toBeDisabled();
  });

  it('предупреждения отделены от ошибок и по умолчанию свёрнуты', async () => {
    const user = userEvent.setup();
    await openScreen();
    await reachPreview(user, invalidPreview());

    const warnings = screen.getByRole('heading', { name: /Предупреждения/ }).closest('section');
    expect(warnings).not.toBeNull();
    const toggle = within(warnings as HTMLElement).getByRole('button', { name: 'Показать' });
    expect(screen.queryByText('У товара не будет цены')).not.toBeInTheDocument();

    await user.click(toggle);
    expect(await screen.findByText('У товара не будет цены')).toBeInTheDocument();
  });

  it('длинный список ошибок раскрывается порциями', async () => {
    const user = userEvent.setup();
    await openScreen();
    const many = Array.from({ length: 25 }, (_, index) =>
      makeIssue({ row: index + 2, message: `Ошибка ${index + 1}` }),
    );
    await reachPreview(
      user,
      makePreview({
        job: makeJob({ status: 'INVALID', can_commit: false, error_count: 25 }),
        valid: false,
        error_count: 25,
        errors: many,
        changes: [],
      }),
    );

    expect(screen.getByText('Ошибка 20')).toBeInTheDocument();
    expect(screen.queryByText('Ошибка 21')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Показать ещё/ }));
    expect(await screen.findByText('Ошибка 25')).toBeInTheDocument();
  });

  it('файл без изменений применять не предлагает', async () => {
    const user = userEvent.setup();
    await openScreen();
    await reachPreview(
      user,
      makePreview({
        summary: {
          rows_total: 12,
          sheets: {},
          products: { create: 0, update: 0, unchanged: 8 },
          categories: { create: 0, update: 0, unchanged: 2 },
          attributes: { create: 0, update: 0, unchanged: 0 },
          attribute_options: { create: 0, update: 0, unchanged: 0 },
        },
        changes: [],
      }),
    );

    expect(screen.getByText('Файл совпадает с каталогом: применять нечего.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Применить импорт' })).toBeDisabled();
  });
});

describe('шаг 3 — применение', () => {
  it('подтверждение, отправка того же файла и итог', async () => {
    const user = userEvent.setup();
    await openScreen();
    await reachPreview(user);
    net.on('POST', COMMIT_URL, jsonResponse(makeCommit()));

    await user.click(screen.getByRole('button', { name: 'Применить импорт' }));
    const dialog = await screen.findByRole('dialog', { name: 'Применить импорт?' });
    await user.click(within(dialog).getByRole('button', { name: 'Применить' }));

    await screen.findByRole('heading', { name: 'Импорт применён' });
    const [call] = net.calls('POST', COMMIT_URL);
    expect(call).toBeDefined();
    expect((call?.[1] as RequestInit).body).toBeInstanceOf(FormData);
    expect(screen.getByText(/Каталог обновлён\./)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Перейти к товарам' })).toHaveAttribute(
      'href',
      '/products',
    );
    // История перечитана после применения
    await waitFor(() => expect(net.calls('GET', HISTORY_URL).length).toBeGreaterThan(1));
  });

  it('отказ в диалоге ничего не отправляет', async () => {
    const user = userEvent.setup();
    await openScreen();
    await reachPreview(user);

    await user.click(screen.getByRole('button', { name: 'Применить импорт' }));
    const dialog = await screen.findByRole('dialog', { name: 'Применить импорт?' });
    await user.click(within(dialog).getByRole('button', { name: 'Отмена' }));

    expect(net.calls('POST', COMMIT_URL)).toHaveLength(0);
  });

  it('неудачное применение показывает причину и ошибки повторной проверки', async () => {
    const user = userEvent.setup();
    await openScreen();
    await reachPreview(user);
    net.on(
      'POST',
      COMMIT_URL,
      errorResponse(422, 'import_validation_failed', 'Каталог изменился после предпросмотра', {
        error_count: 1,
        errors: [
          {
            sheet: 'Products',
            row: 2,
            column: 'slug',
            code: 'slug_taken',
            message: 'Адрес уже занят другим товаром',
          },
        ],
      }),
    );

    await user.click(screen.getByRole('button', { name: 'Применить импорт' }));
    const dialog = await screen.findByRole('dialog', { name: 'Применить импорт?' });
    await user.click(within(dialog).getByRole('button', { name: 'Применить' }));

    expect(
      (await screen.findAllByText(/Каталог изменился после предпросмотра/)).length,
    ).toBeGreaterThan(0);
    expect(screen.getByText('Адрес уже занят другим товаром')).toBeInTheDocument();
    // Экран остаётся на шаге проверки
    expect(screen.getByRole('heading', { name: 'Проверка файла' })).toBeInTheDocument();
  });
});

describe('история импортов', () => {
  it('показывает файлы, статусы и счётчики', async () => {
    await openScreen('CONTENT_MANAGER', [
      makeJob({ status: 'COMMITTED', committed_at: '2026-09-17T06:05:00Z', can_commit: false }),
      makeJob({
        uuid: 'b2c3d4e5-0000-4000-8000-000000000002',
        status: 'FAILED',
        failure_code: 'import_preview_expired',
        error_count: 3,
        warning_count: 1,
      }),
    ]);

    const table = await screen.findByRole('table', { name: 'История импортов' });
    expect(within(table).getAllByText('catalog.xlsx')).toHaveLength(2);
    expect(within(table).getByText('Применён')).toBeInTheDocument();
    expect(within(table).getByText('Не применён')).toBeInTheDocument();
    expect(within(table).getByText('Предпросмотр устарел')).toBeInTheDocument();
    expect(within(table).getByText('3 ош.')).toBeInTheDocument();
  });

  it('фильтр по статусу уходит в адрес и в запрос', async () => {
    const user = userEvent.setup();
    await openScreen();

    await user.selectOptions(screen.getByLabelText('Статус'), 'COMMITTED');

    await waitFor(() =>
      expect(routerReplace).toHaveBeenCalledWith('/import-export?status=COMMITTED', {
        scroll: false,
      }),
    );
  });

  it('карточка импорта открывается с ошибками', async () => {
    const user = userEvent.setup();
    await openScreen('CONTENT_MANAGER', [makeJob({ status: 'INVALID', error_count: 1 })]);
    net.on(
      'GET',
      JOB_URL,
      jsonResponse(
        makeJobDetail({
          status: 'INVALID',
          error_count: 1,
          errors: [makeIssue({ message: 'Категория не найдена' })],
        }),
      ),
    );

    const table = await screen.findByRole('table', { name: 'История импортов' });
    // findAll, а не getAll: таблица отрисована раньше строк — до ответа
    // сервера в ней скелетон, и getAll гоняется с загрузкой.
    const rows = await within(table).findAllByText('catalog.xlsx');
    await user.click(rows[0] as HTMLElement);

    const drawer = await screen.findByRole('dialog', { name: 'Импорт' });
    expect(await within(drawer).findByText('Категория не найдена')).toBeInTheDocument();
    expect(net.calls('GET', JOB_URL)).toHaveLength(1);
  });

  it('до ответа сервера таблица показывает скелетон', async () => {
    signInAs(net, 'CONTENT_MANAGER');
    navigationState.pathname = '/import-export';
    let release: (value: Response) => void = () => {};
    net.on('GET', HISTORY_URL, () => new Promise<Response>((resolve) => (release = resolve)));
    renderInPanel(<ImportExportScreen />);

    const table = await screen.findByRole('table', { name: 'История импортов' });
    expect(table).toHaveAttribute('aria-busy', 'true');

    release(jsonResponse(page([makeJob()])));
    expect(await within(table).findByText('catalog.xlsx')).toBeInTheDocument();
    expect(table).not.toHaveAttribute('aria-busy');
  });

  it('пустая история объясняет, что будет в разделе', async () => {
    await openScreen('CONTENT_MANAGER', []);
    const table = await screen.findByRole('table', { name: 'История импортов' });
    expect(await within(table).findByText('Импортов пока не было')).toBeInTheDocument();
  });

  it('ошибка загрузки истории даёт кнопку «Повторить»', async () => {
    signInAs(net, 'CONTENT_MANAGER');
    navigationState.pathname = '/import-export';
    net.on('GET', HISTORY_URL, errorResponse(500, 'internal_error', 'Ошибка сервера'));
    renderInPanel(<ImportExportScreen />);

    const table = await screen.findByRole('table', { name: 'История импортов' });
    expect(await within(table).findByText('Не удалось загрузить данные')).toBeInTheDocument();
    expect(within(table).getByRole('button', { name: 'Повторить' })).toBeInTheDocument();
  });

  it('мобильная карточка показывает файл и статус', async () => {
    await openScreen();
    const mobile = await screen.findByTestId('mobile-list');
    expect(within(mobile).getByText('catalog.xlsx')).toBeInTheDocument();
    expect(within(mobile).getByText('Проверен')).toBeInTheDocument();
  });
});

describe('права', () => {
  it('MANAGER (только чтение каталога) проверяет файл, но не применяет', async () => {
    const user = userEvent.setup();
    await openScreen('MANAGER');

    expect(screen.getByRole('button', { name: 'Скачать каталог (XLSX)' })).toBeInTheDocument();
    await reachPreview(user);

    expect(screen.queryByRole('button', { name: 'Применить импорт' })).not.toBeInTheDocument();
    expect(
      screen.getByText(/Применять импорт может сотрудник с правом изменения каталога/),
    ).toBeInTheDocument();
  });

  it('без catalog.read раздел закрыт', async () => {
    window.localStorage.setItem('oinau.admin.session', '1');
    net.on('POST', '/api/v1/admin/auth/refresh', tokens('access'));
    net.on('GET', '/api/v1/admin/auth/me', makeUser('VIEWER', { permissions: [] }));
    navigationState.pathname = '/import-export';

    renderInPanel(<ImportExportScreen />);

    expect(await screen.findByText('Нет доступа')).toBeInTheDocument();
    expect(net.calls('GET', HISTORY_URL)).toHaveLength(0);
  });

  it('аноним отправляется на вход', async () => {
    navigationState.pathname = '/import-export';
    net.on('POST', '/api/v1/admin/auth/refresh', errorResponse(401, 'unauthenticated', 'x'));
    window.localStorage.setItem('oinau.admin.session', '1');

    renderInPanel(<ImportExportScreen />);

    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith('/login?next=%2Fimport-export'));
  });
});
