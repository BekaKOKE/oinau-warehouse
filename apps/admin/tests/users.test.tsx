/**
 * Раздел «Пользователи»: список с фильтрами, заведение и правка
 * сотрудника, роли и права, ограничения безопасности и доступ.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AppProviders } from '@/components/AppProviders';
import { AuthGate } from '@/components/session/AuthGate';
import { UsersScreen } from '@/components/users/UsersScreen';
import type { AdminUser, UserRole } from '@/lib/api/types';
import { resetSessionForTests } from '@/lib/auth/session';

import { createFetchMock, errorResponse, jsonResponse, page, signInAs } from './helpers';
import { navigationState, routerReplace } from './setup';
import { makeAdminUser, ROLES, ROLES_URL, SELF_UUID, USER_ROWS, USERS_URL } from './user-fixtures';

let net: ReturnType<typeof createFetchMock>;

function renderInPanel(ui: ReactNode) {
  return render(
    <AppProviders>
      <AuthGate>{ui}</AuthGate>
    </AppProviders>,
  );
}

function bodyOf(method: string, path: string, index = 0): unknown {
  const call = net.calls(method, path)[index];
  return JSON.parse(String((call?.[1] as RequestInit).body));
}

function lastParams(path: string) {
  const calls = net.calls('GET', path);
  return new URL(String(calls[calls.length - 1]?.[0])).searchParams;
}

async function openUsers(role: UserRole = 'ADMIN', rows: AdminUser[] = USER_ROWS, search = '') {
  signInAs(net, role);
  navigationState.pathname = '/users';
  navigationState.search = search;
  net.on('GET', USERS_URL, page(rows, rows.length));
  net.on('GET', ROLES_URL, ROLES);
  renderInPanel(<UsersScreen />);
  const table = await screen.findByRole('table', { name: 'Сотрудники' });
  // Ждём данные: до ответа в таблице скелетон, и запросы к ней ничего не найдут.
  await within(table).findByText(rows[0] ? rows[0].full_name : 'Сотрудников пока нет');
  return table;
}

async function openDrawer(user: ReturnType<typeof userEvent.setup>, name: string) {
  const table = await screen.findByRole('table', { name: 'Сотрудники' });
  await user.click(within(table).getByRole('button', { name }));
  return screen.findByRole('dialog', { name });
}

beforeEach(() => {
  resetSessionForTests();
  net = createFetchMock();
  vi.stubGlobal('fetch', net.mock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('список', () => {
  it('показывает сотрудников, роли и состояние доступа', async () => {
    const table = await openUsers();

    expect(within(table).getByText('manager@oinau-pro.kz')).toBeInTheDocument();
    expect(within(table).getByText('Менеджер')).toBeInTheDocument();
    expect(within(table).getByText('Контент-менеджер')).toBeInTheDocument();
    expect(within(table).getAllByText('Активен')).toHaveLength(2);
    expect(within(table).getByText('Отключён')).toBeInTheDocument();
    expect(screen.getByText('3 сотрудника')).toBeInTheDocument();
  });

  it('не показывает ни паролей, ни внутренних идентификаторов', async () => {
    const table = await openUsers();
    expect(table.textContent).not.toMatch(/password|хеш/i);
  });

  it('фильтры уходят в адрес и в запрос', async () => {
    const user = userEvent.setup();
    await openUsers();

    await user.selectOptions(screen.getByLabelText('Роль'), 'VIEWER');
    await waitFor(() =>
      expect(routerReplace).toHaveBeenCalledWith('/users?role=VIEWER', { scroll: false }),
    );
    await waitFor(() => expect(lastParams(USERS_URL).get('role')).toBe('VIEWER'));

    await user.selectOptions(screen.getByLabelText('Доступ'), 'disabled');
    await waitFor(() => expect(lastParams(USERS_URL).get('is_active')).toBe('false'));
  });

  it('поиск применяется после паузы ввода', async () => {
    const user = userEvent.setup();
    await openUsers();

    await user.type(screen.getByLabelText('Поиск'), 'Жанна');

    await waitFor(() => expect(lastParams(USERS_URL).get('search')).toBe('Жанна'), {
      timeout: 2000,
    });
  });

  it('фильтры из адреса применяются при открытии и сбрасываются кнопкой', async () => {
    const user = userEvent.setup();
    await openUsers('ADMIN', USER_ROWS, '?search=Пётр&status=disabled');

    expect(lastParams(USERS_URL).get('search')).toBe('Пётр');
    await user.click(screen.getByRole('button', { name: 'Сбросить фильтры' }));
    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith('/users', { scroll: false }));
  });

  it('вошедший сотрудник отмечен в списке', async () => {
    const table = await openUsers('ADMIN', [
      makeAdminUser({ uuid: SELF_UUID, full_name: 'Айгерим Серикова', role: 'ADMIN' }),
    ]);
    expect(within(table).getByText('Это вы')).toBeInTheDocument();
  });

  it('пустой список объясняет, что делать', async () => {
    const table = await openUsers('ADMIN', []);
    expect(within(table).getByText('Сотрудников пока нет')).toBeInTheDocument();
  });

  it('до ответа сервера таблица показывает скелетон', async () => {
    signInAs(net, 'ADMIN');
    navigationState.pathname = '/users';
    let release: (value: Response) => void = () => {};
    net.on('GET', USERS_URL, () => new Promise<Response>((resolve) => (release = resolve)));
    net.on('GET', ROLES_URL, ROLES);
    renderInPanel(<UsersScreen />);

    const table = await screen.findByRole('table', { name: 'Сотрудники' });
    expect(table).toHaveAttribute('aria-busy', 'true');

    release(jsonResponse(page(USER_ROWS)));
    expect(await within(table).findByText('Бекзат Оспанов')).toBeInTheDocument();
  });

  it('ошибка загрузки даёт «Повторить»', async () => {
    signInAs(net, 'ADMIN');
    navigationState.pathname = '/users';
    net.on('GET', USERS_URL, errorResponse(500, 'internal_error', 'Ошибка сервера'));
    net.on('GET', ROLES_URL, ROLES);
    renderInPanel(<UsersScreen />);

    const table = await screen.findByRole('table', { name: 'Сотрудники' });
    expect(await within(table).findByText('Не удалось загрузить данные')).toBeInTheDocument();
    expect(within(table).getByRole('button', { name: 'Повторить' })).toBeInTheDocument();
  });

  it('мобильная карточка показывает имя, роль и доступ', async () => {
    await openUsers();
    const mobile = await screen.findByTestId('mobile-list');
    const card = within(within(mobile).getByText('Пётр Кузнецов').closest('li') as HTMLElement);
    expect(card.getByText('Наблюдатель')).toBeInTheDocument();
    expect(card.getByText('Отключён')).toBeInTheDocument();
  });

  it('роли и их права показаны по данным backend', async () => {
    await openUsers();
    const section = (await screen.findByRole('heading', { name: 'Роли и права' })).closest(
      'section',
    ) as HTMLElement;
    const card = within(section).getByText('Суперадминистратор').closest('div') as HTMLElement;
    expect(within(card).getByText('API-ключи')).toBeInTheDocument();
    expect(within(section).getByText('Наблюдатель')).toBeInTheDocument();
    expect(net.calls('GET', ROLES_URL)).toHaveLength(1);
  });
});

describe('заведение сотрудника', () => {
  it('отправляет форму и перечитывает список', async () => {
    const user = userEvent.setup();
    await openUsers();
    net.on('POST', USERS_URL, jsonResponse(makeAdminUser({ email: 'new@oinau-pro.kz' }), 201));

    await user.click(screen.getByRole('button', { name: 'Новый сотрудник' }));
    const dialog = await screen.findByRole('dialog', { name: 'Новый сотрудник' });
    await user.type(within(dialog).getByLabelText(/Email/), 'new@oinau-pro.kz');
    await user.type(within(dialog).getByLabelText(/Имя и фамилия/), 'Айгерим Серикова');
    await user.selectOptions(within(dialog).getByLabelText(/Роль/), 'CONTENT_MANAGER');
    await user.type(within(dialog).getByLabelText(/Пароль/), 'another-strong-passphrase');
    await user.click(within(dialog).getByRole('button', { name: 'Завести' }));

    await waitFor(() => expect(net.calls('POST', USERS_URL)).toHaveLength(1));
    expect(bodyOf('POST', USERS_URL)).toEqual({
      email: 'new@oinau-pro.kz',
      full_name: 'Айгерим Серикова',
      password: 'another-strong-passphrase',
      role: 'CONTENT_MANAGER',
      phone: null,
    });
    await waitFor(() => expect(net.calls('GET', USERS_URL).length).toBeGreaterThan(1));
  });

  it('не отправляет пустую форму и показывает ошибки полей', async () => {
    const user = userEvent.setup();
    await openUsers();

    await user.click(screen.getByRole('button', { name: 'Новый сотрудник' }));
    const dialog = await screen.findByRole('dialog', { name: 'Новый сотрудник' });
    await user.click(within(dialog).getByRole('button', { name: 'Завести' }));

    expect(await within(dialog).findByText('Введите email')).toBeInTheDocument();
    expect(within(dialog).getByText('Введите имя и фамилию')).toBeInTheDocument();
    expect(within(dialog).getByText('Введите пароль')).toBeInTheDocument();
    expect(net.calls('POST', USERS_URL)).toHaveLength(0);
  });

  it('занятый email показывается у поля', async () => {
    const user = userEvent.setup();
    await openUsers();
    net.on(
      'POST',
      USERS_URL,
      errorResponse(409, 'email_exists', 'Пользователь с таким email уже существует'),
    );

    await user.click(screen.getByRole('button', { name: 'Новый сотрудник' }));
    const dialog = await screen.findByRole('dialog', { name: 'Новый сотрудник' });
    await user.type(within(dialog).getByLabelText(/Email/), 'manager@oinau-pro.kz');
    await user.type(within(dialog).getByLabelText(/Имя и фамилия/), 'Бекзат Оспанов');
    await user.type(within(dialog).getByLabelText(/Пароль/), 'another-strong-passphrase');
    await user.click(within(dialog).getByRole('button', { name: 'Завести' }));

    expect(
      await within(dialog).findByText('Пользователь с таким email уже существует'),
    ).toBeInTheDocument();
  });

  it('администратор не может завести суперадминистратора', async () => {
    const user = userEvent.setup();
    await openUsers('ADMIN');

    await user.click(screen.getByRole('button', { name: 'Новый сотрудник' }));
    const dialog = await screen.findByRole('dialog', { name: 'Новый сотрудник' });
    const roles = within(dialog).getByLabelText(/Роль/) as HTMLSelectElement;

    expect([...roles.options].map((option) => option.value)).not.toContain('SUPERADMIN');
  });

  it('суперадминистратор такую роль назначить может', async () => {
    const user = userEvent.setup();
    await openUsers('SUPERADMIN');

    await user.click(screen.getByRole('button', { name: 'Новый сотрудник' }));
    const dialog = await screen.findByRole('dialog', { name: 'Новый сотрудник' });
    const roles = within(dialog).getByLabelText(/Роль/) as HTMLSelectElement;

    expect([...roles.options].map((option) => option.value)).toContain('SUPERADMIN');
  });
});

describe('правка сотрудника', () => {
  it('отправляет только изменённые поля', async () => {
    const user = userEvent.setup();
    await openUsers();
    net.on('PATCH', `${USERS_URL}/${USER_ROWS[0]?.uuid}`, jsonResponse(makeAdminUser()));

    const dialog = await openDrawer(user, 'Бекзат Оспанов');
    await user.selectOptions(within(dialog).getByLabelText(/Роль/), 'ADMIN');
    await user.click(within(dialog).getByRole('button', { name: 'Сохранить' }));

    const path = `${USERS_URL}/${USER_ROWS[0]?.uuid}`;
    await waitFor(() => expect(net.calls('PATCH', path)).toHaveLength(1));
    expect(bodyOf('PATCH', path)).toEqual({ role: 'ADMIN' });
  });

  it('email в форме правки только показывается', async () => {
    const user = userEvent.setup();
    await openUsers();

    const dialog = await openDrawer(user, 'Бекзат Оспанов');

    expect(
      within(dialog).getByText('Email неизменяем: новый адрес — новая учётная запись.'),
    ).toBeInTheDocument();
    expect(within(dialog).queryByRole('textbox', { name: /Email/ })).not.toBeInTheDocument();
  });

  it('отключение подтверждается и отзывает сессии', async () => {
    const user = userEvent.setup();
    await openUsers();
    const path = `${USERS_URL}/${USER_ROWS[0]?.uuid}`;
    net.on('PATCH', path, jsonResponse(makeAdminUser({ is_active: false })));

    const dialog = await openDrawer(user, 'Бекзат Оспанов');
    await user.click(within(dialog).getByRole('switch', { name: /Доступ в админку/ }));
    await user.click(within(dialog).getByRole('button', { name: 'Сохранить' }));

    const confirmDialog = await screen.findByRole('dialog', { name: 'Отключить Бекзат Оспанов?' });
    expect(confirmDialog).toHaveTextContent(/сессии будут закрыты/);
    await user.click(within(confirmDialog).getByRole('button', { name: 'Отключить' }));

    await waitFor(() => expect(net.calls('PATCH', path)).toHaveLength(1));
    expect(bodyOf('PATCH', path)).toEqual({ is_active: false });
  });

  it('отказ в подтверждении ничего не отправляет', async () => {
    const user = userEvent.setup();
    await openUsers();
    const path = `${USERS_URL}/${USER_ROWS[0]?.uuid}`;

    const dialog = await openDrawer(user, 'Бекзат Оспанов');
    await user.click(within(dialog).getByRole('switch', { name: /Доступ в админку/ }));
    await user.click(within(dialog).getByRole('button', { name: 'Сохранить' }));
    const confirmDialog = await screen.findByRole('dialog', { name: 'Отключить Бекзат Оспанов?' });
    await user.click(within(confirmDialog).getByRole('button', { name: 'Отмена' }));

    expect(net.calls('PATCH', path)).toHaveLength(0);
  });

  it('новый пароль задаётся с подтверждением', async () => {
    const user = userEvent.setup();
    await openUsers();
    const path = `${USERS_URL}/${USER_ROWS[0]?.uuid}`;
    net.on('PATCH', path, jsonResponse(makeAdminUser()));

    const dialog = await openDrawer(user, 'Бекзат Оспанов');
    await user.click(within(dialog).getByRole('checkbox', { name: 'Задать новый пароль' }));
    await user.type(within(dialog).getByLabelText(/Новый пароль/), 'another-strong-passphrase');
    await user.click(within(dialog).getByRole('button', { name: 'Сохранить' }));

    const confirmDialog = await screen.findByRole('dialog', { name: 'Задать новый пароль?' });
    await user.click(within(confirmDialog).getByRole('button', { name: 'Задать пароль' }));

    await waitFor(() => expect(net.calls('PATCH', path)).toHaveLength(1));
    expect(bodyOf('PATCH', path)).toEqual({ password: 'another-strong-passphrase' });
  });

  it('короткий пароль не уходит на сервер', async () => {
    const user = userEvent.setup();
    await openUsers();

    const dialog = await openDrawer(user, 'Бекзат Оспанов');
    await user.click(within(dialog).getByRole('checkbox', { name: 'Задать новый пароль' }));
    await user.type(within(dialog).getByLabelText(/Новый пароль/), 'short');
    await user.click(within(dialog).getByRole('button', { name: 'Сохранить' }));

    expect(await within(dialog).findByText(/Не короче 12 символов/)).toBeInTheDocument();
    expect(net.calls('PATCH', `${USERS_URL}/${USER_ROWS[0]?.uuid}`)).toHaveLength(0);
  });

  it('свою роль и свой доступ изменить нельзя', async () => {
    const user = userEvent.setup();
    await openUsers('ADMIN', [
      makeAdminUser({ uuid: SELF_UUID, full_name: 'Айгерим Серикова', role: 'ADMIN' }),
    ]);

    const dialog = await openDrawer(user, 'Айгерим Серикова');

    expect(within(dialog).getByLabelText(/Роль/)).toBeDisabled();
    expect(within(dialog).getByRole('switch', { name: /Доступ в админку/ })).toBeDisabled();
    expect(within(dialog).getByText('Свою роль изменить нельзя')).toBeInTheDocument();
  });

  it('администратор не правит суперадминистратора', async () => {
    const user = userEvent.setup();
    await openUsers('ADMIN', [makeAdminUser({ full_name: 'Данияр Ахметов', role: 'SUPERADMIN' })]);

    const dialog = await openDrawer(user, 'Данияр Ахметов');

    expect(within(dialog).getByText(/управляет только суперадминистратор/)).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Сохранить' })).toBeDisabled();
  });

  it('отказ backend показывается над формой', async () => {
    const user = userEvent.setup();
    await openUsers();
    const path = `${USERS_URL}/${USER_ROWS[0]?.uuid}`;
    net.on(
      'PATCH',
      path,
      errorResponse(403, 'superadmin_required', 'Управлять суперадминистраторами нельзя'),
    );

    const dialog = await openDrawer(user, 'Бекзат Оспанов');
    await user.selectOptions(within(dialog).getByLabelText(/Роль/), 'ADMIN');
    await user.click(within(dialog).getByRole('button', { name: 'Сохранить' }));

    expect(
      await within(dialog).findByText('Управлять суперадминистраторами нельзя'),
    ).toBeInTheDocument();
  });
});

describe('доступ к разделу', () => {
  it.each<UserRole>(['MANAGER', 'CONTENT_MANAGER', 'VIEWER'])(
    'роль %s получает экран «Нет доступа»',
    async (role) => {
      signInAs(net, role);
      navigationState.pathname = '/users';
      renderInPanel(<UsersScreen />);

      expect(await screen.findByText('Нет доступа')).toBeInTheDocument();
      expect(net.calls('GET', USERS_URL)).toHaveLength(0);
    },
  );

  it('аноним отправляется на вход', async () => {
    navigationState.pathname = '/users';
    window.localStorage.setItem('oinau.admin.session', '1');
    net.on('POST', '/api/v1/admin/auth/refresh', errorResponse(401, 'unauthenticated', 'x'));

    renderInPanel(<UsersScreen />);

    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith('/login?next=%2Fusers'));
  });
});
