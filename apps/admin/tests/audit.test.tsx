/**
 * Раздел «Аудит»: журнал, фильтры, карточка записи и доступ.
 *
 * Журнал только читается: тесты проверяют, что экран не отправляет
 * ничего, кроме GET, и не показывает секретов.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AppProviders } from '@/components/AppProviders';
import { AuditScreen } from '@/components/audit/AuditScreen';
import { AuthGate } from '@/components/session/AuthGate';
import type { AuditLogEntry, UserRole } from '@/lib/api/types';
import { resetSessionForTests } from '@/lib/auth/session';

import { AUDIT_ROWS, AUDIT_URL, makeAuditEntry, STAFF_UUID } from './audit-fixtures';
import { createFetchMock, errorResponse, jsonResponse, page, signInAs } from './helpers';
import { navigationState, routerReplace } from './setup';
import { ROLES_URL, USER_ROWS, USERS_URL } from './user-fixtures';

let net: ReturnType<typeof createFetchMock>;

function renderInPanel(ui: ReactNode) {
  return render(
    <AppProviders>
      <AuthGate>{ui}</AuthGate>
    </AppProviders>,
  );
}

function lastParams(path: string) {
  const calls = net.calls('GET', path);
  return new URL(String(calls[calls.length - 1]?.[0])).searchParams;
}

async function openAudit(
  role: UserRole = 'ADMIN',
  rows: AuditLogEntry[] = AUDIT_ROWS,
  search = '',
  total = rows.length,
) {
  signInAs(net, role);
  navigationState.pathname = '/audit';
  navigationState.search = search;
  net.on('GET', AUDIT_URL, page(rows, total));
  net.on('GET', USERS_URL, page(USER_ROWS, USER_ROWS.length));
  net.on('GET', ROLES_URL, []);
  renderInPanel(<AuditScreen />);
  const table = await screen.findByRole('table', { name: 'Журнал аудита' });
  // До ответа в таблице скелетон — ждём строки (или объяснение пустоты).
  if (rows.length > 0) await within(table).findAllByRole('button', { name: 'Подробно' });
  else await within(table).findByText('Журнал пуст');
  return table;
}

beforeEach(() => {
  resetSessionForTests();
  net = createFetchMock();
  vi.stubGlobal('fetch', net.mock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('журнал', () => {
  it('показывает время, действие, объект и автора записи', async () => {
    const table = await openAudit();

    expect(within(table).getAllByText('Товар изменён')).toHaveLength(2);
    expect(within(table).getByText('Цены изменены')).toBeInTheDocument();
    expect(within(table).getAllByText('Данияр Ахметов')).toHaveLength(2);
    // Действие импорта выполнено не сотрудником — показывается источник.
    expect(within(table).getByText('Импорт из файла')).toBeInTheDocument();
    expect(screen.getByText('3 записи')).toBeInTheDocument();
    // Объект с известным адресом — ссылка в раздел.
    expect(within(table).getAllByRole('link', { name: '#42' })[0]).toHaveAttribute(
      'href',
      '/products/42',
    );
  });

  it('неизвестное действие backend показывается кодом, а не теряется', async () => {
    const table = await openAudit('ADMIN', [
      makeAuditEntry({ id: 1, action: 'telegram.message_sent', entity_type: 'notification' }),
    ]);

    // Подпись и код: подписи для действия нет, показывается сам код.
    expect(within(table).getAllByText('telegram.message_sent')).toHaveLength(2);
    expect(within(table).getByText('notification')).toBeInTheDocument();
  });

  it('запрашивает первую страницу по умолчанию и листает', async () => {
    await openAudit('ADMIN', AUDIT_ROWS, '', 90);
    const user = userEvent.setup();

    expect(lastParams(AUDIT_URL).get('page_size')).toBe('30');
    await user.click(screen.getByRole('button', { name: 'Следующая страница' }));

    await waitFor(() =>
      expect(routerReplace).toHaveBeenCalledWith('/audit?page=2', expect.anything()),
    );
    await waitFor(() => expect(lastParams(AUDIT_URL).get('page')).toBe('2'));
  });

  it('журнал только читается: ничего, кроме GET, не отправляется', async () => {
    await openAudit();

    const methods = net.mock.mock.calls
      .filter(([url]) => new URL(String(url)).pathname === AUDIT_URL)
      .map(([, init]) => (init as RequestInit | undefined)?.method ?? 'GET');
    expect(new Set(methods)).toEqual(new Set(['GET']));
  });
});

describe('фильтры', () => {
  it('раздел и действие уходят в запрос и в адрес', async () => {
    await openAudit();
    const user = userEvent.setup();

    await user.selectOptions(screen.getByLabelText('Раздел'), 'request');
    await waitFor(() => expect(lastParams(AUDIT_URL).get('entity_type')).toBe('request'));

    // Список действий сузился до действий выбранного раздела.
    const actions = within(screen.getByLabelText('Действие') as HTMLSelectElement)
      .getAllByRole('option')
      .map((option) => option.textContent);
    expect(actions).toContain('Статус заявки изменён');
    expect(actions).not.toContain('Товар создан');

    await user.selectOptions(screen.getByLabelText('Действие'), 'request.status_updated');
    await waitFor(() => expect(lastParams(AUDIT_URL).get('action')).toBe('request.status_updated'));
    expect(routerReplace).toHaveBeenLastCalledWith(
      '/audit?action=request.status_updated&entity=request',
      expect.anything(),
    );
  });

  it('смена раздела сбрасывает выбранное действие другого раздела', async () => {
    await openAudit('ADMIN', AUDIT_ROWS, 'action=catalog.product_created&entity=product');
    const user = userEvent.setup();

    await user.selectOptions(screen.getByLabelText('Раздел'), 'request');

    await waitFor(() => expect(lastParams(AUDIT_URL).get('action')).toBeNull());
    expect(lastParams(AUDIT_URL).get('entity_type')).toBe('request');
  });

  it('период уходит границами дня Алматы, обратный период не запрашивается', async () => {
    await openAudit();
    const user = userEvent.setup();
    const before = net.calls('GET', AUDIT_URL).length;

    await user.type(screen.getByLabelText('С даты'), '2026-09-17');
    await waitFor(() =>
      expect(lastParams(AUDIT_URL).get('created_from')).toMatch(/^2026-09-17T00:00:00/),
    );

    await user.type(screen.getByLabelText('по'), '2026-09-01');
    expect(await screen.findByText('Дата «с» позже даты «по»')).toBeInTheDocument();
    expect(screen.getAllByText('Период задан наоборот').length).toBeGreaterThan(0);
    await waitFor(() =>
      expect(net.calls('GET', AUDIT_URL).length).toBeGreaterThanOrEqual(before + 1),
    );
    expect(lastParams(AUDIT_URL).get('created_to')).toBeNull();
  });

  it('фильтр по сотруднику берёт список из backend и уходит как user_uuid', async () => {
    await openAudit();
    const user = userEvent.setup();

    await waitFor(() => expect(net.calls('GET', USERS_URL).length).toBe(1));
    await user.selectOptions(screen.getByLabelText('Сотрудник'), USER_ROWS[0]!.uuid);

    await waitFor(() => expect(lastParams(AUDIT_URL).get('user_uuid')).toBe(USER_ROWS[0]!.uuid));
  });

  it('фильтры читаются из адреса и сбрасываются одной кнопкой', async () => {
    await openAudit('ADMIN', AUDIT_ROWS, `actor=import&entity=product&user=${STAFF_UUID}`);
    const user = userEvent.setup();

    const params = lastParams(AUDIT_URL);
    expect(params.get('actor')).toBe('import');
    expect(params.get('entity_type')).toBe('product');
    expect(params.get('user_uuid')).toBe(STAFF_UUID);

    await user.click(screen.getByRole('button', { name: 'Сбросить фильтры' }));
    await waitFor(() =>
      expect(routerReplace).toHaveBeenLastCalledWith('/audit', expect.anything()),
    );
  });

  it('фильтр по объекту из адреса показывается снимаемой меткой', async () => {
    await openAudit('ADMIN', AUDIT_ROWS, 'entity=product&entity_id=42');
    const user = userEvent.setup();

    expect(lastParams(AUDIT_URL).get('entity_id')).toBe('42');
    await user.click(screen.getByRole('button', { name: /объект #42/ }));

    await waitFor(() => expect(lastParams(AUDIT_URL).get('entity_id')).toBeNull());
  });
});

describe('карточка записи', () => {
  it('показывает изменённые поля парами «было → стало»', async () => {
    const table = await openAudit();
    const user = userEvent.setup();

    await user.click(within(table).getAllByRole('button', { name: 'Подробно' })[1]!);
    const dialog = await screen.findByRole('dialog', { name: 'Цены изменены' });

    expect(within(dialog).getByText('Цена')).toBeInTheDocument();
    expect(within(dialog).getByText('3500.00')).toBeInTheDocument();
    expect(within(dialog).getByText('3200.00')).toBeInTheDocument();
    expect(within(dialog).getByText('pricing.updated')).toBeInTheDocument();
  });

  it('запись без изменений объясняет, что подробностей нет', async () => {
    const table = await openAudit('ADMIN', [
      makeAuditEntry({ id: 5, action: 'auth.login_success', entity_type: 'user', changes: {} }),
    ]);
    const user = userEvent.setup();

    await user.click(within(table).getByRole('button', { name: 'Подробно' }));
    const dialog = await screen.findByRole('dialog', { name: 'Вход в админку' });
    expect(within(dialog).getByText('Подробностей нет')).toBeInTheDocument();
  });

  it('секретные поля не выводятся, даже если backend их пришлёт', async () => {
    const table = await openAudit('ADMIN', [
      makeAuditEntry({
        id: 6,
        action: 'user.updated',
        entity_type: 'user',
        changes: {
          password: 'p@ssw0rd-very-secret',
          storage_key: 'products/2026/x.jpg',
          role: 'ADMIN',
        },
      }),
    ]);
    const user = userEvent.setup();

    await user.click(within(table).getByRole('button', { name: 'Подробно' }));
    const dialog = await screen.findByRole('dialog', { name: 'Сотрудник изменён' });

    expect(within(dialog).getAllByText('скрыто')).toHaveLength(2);
    expect(screen.queryByText(/p@ssw0rd/)).not.toBeInTheDocument();
    expect(screen.queryByText(/products\/2026/)).not.toBeInTheDocument();
    expect(within(dialog).getByText('ADMIN')).toBeInTheDocument();
  });

  it('по идентификатору запроса можно отфильтровать весь запрос', async () => {
    const table = await openAudit();
    const user = userEvent.setup();

    await user.click(within(table).getAllByRole('button', { name: 'Подробно' })[0]!);
    const dialog = await screen.findByRole('dialog', { name: 'Товар изменён' });
    await user.click(within(dialog).getByRole('button', { name: 'req-7f3a' }));

    await waitFor(() => expect(lastParams(AUDIT_URL).get('request_id')).toBe('req-7f3a'));
  });
});

describe('состояния и доступ', () => {
  it('пустой журнал объясняет, что здесь появится', async () => {
    await openAudit('ADMIN', []);
    expect(screen.getAllByText('Журнал пуст').length).toBeGreaterThan(0);
  });

  it('ошибка загрузки предлагает повтор', async () => {
    signInAs(net, 'ADMIN');
    navigationState.pathname = '/audit';
    net.on('GET', AUDIT_URL, errorResponse(500, 'internal_error', 'Внутренняя ошибка сервера'));
    net.on('GET', USERS_URL, page(USER_ROWS, USER_ROWS.length));
    renderInPanel(<AuditScreen />);

    expect(await screen.findAllByText('Не удалось загрузить данные')).not.toHaveLength(0);
    const user = userEvent.setup();
    net.on('GET', AUDIT_URL, page(AUDIT_ROWS, AUDIT_ROWS.length));
    await user.click(screen.getAllByRole('button', { name: 'Повторить' })[0]!);

    expect(await screen.findAllByText('Цены изменены')).not.toHaveLength(0);
  });

  it('403 backend показывает «Нет доступа»', async () => {
    signInAs(net, 'ADMIN');
    navigationState.pathname = '/audit';
    net.on('GET', AUDIT_URL, errorResponse(403, 'forbidden', 'Недостаточно прав'));
    net.on('GET', USERS_URL, page([], 0));
    renderInPanel(<AuditScreen />);

    expect(await screen.findAllByText('Нет доступа')).not.toHaveLength(0);
  });

  it.each(['MANAGER', 'CONTENT_MANAGER', 'VIEWER'] as const)(
    'роль %s по прямому адресу видит «Нет доступа» и не запрашивает журнал',
    async (role) => {
      signInAs(net, role);
      navigationState.pathname = '/audit';
      renderInPanel(<AuditScreen />);

      expect(await screen.findByText('Нет доступа')).toBeInTheDocument();
      expect(net.calls('GET', AUDIT_URL)).toHaveLength(0);
      expect(net.calls('GET', USERS_URL)).toHaveLength(0);
    },
  );

  it('без права на сотрудников фильтр по сотруднику не показывается', async () => {
    signInAs(net, 'ADMIN');
    net.on('GET', '/api/v1/admin/auth/me', () =>
      jsonResponse({
        uuid: STAFF_UUID,
        email: 'audit@oinau-pro.kz',
        full_name: 'Аудитор Аудиторов',
        phone: null,
        role: 'ADMIN',
        is_active: true,
        last_login_at: null,
        created_at: '2026-09-01T08:00:00Z',
        updated_at: '2026-09-01T08:00:00Z',
        // роль та же, но прав на сотрудников у этой учётной записи нет
        permissions: ['audit.read'],
      }),
    );
    navigationState.pathname = '/audit';
    net.on('GET', AUDIT_URL, page(AUDIT_ROWS, AUDIT_ROWS.length));
    renderInPanel(<AuditScreen />);

    await screen.findByRole('table', { name: 'Журнал аудита' });
    expect(screen.queryByLabelText('Сотрудник')).not.toBeInTheDocument();
    expect(net.calls('GET', USERS_URL)).toHaveLength(0);
  });
});
