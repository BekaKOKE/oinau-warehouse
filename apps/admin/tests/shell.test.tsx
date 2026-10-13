/**
 * Вход, шлюз сессии, навигация по правам и дашборд.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import PanelLayout from '@/app/(panel)/layout';
import { AuthGate } from '@/components/session/AuthGate';
import { AppProviders } from '@/components/AppProviders';
import { LoginScreen } from '@/components/auth/LoginScreen';
import { Dashboard } from '@/components/dashboard/Dashboard';
import { useConfirm } from '@/components/ui/Dialog';
import type { UserRole } from '@/lib/api/types';
import { resetSessionForTests, SESSION_HINT_KEY } from '@/lib/auth/session';

import { CATALOG_SUMMARY, CONTENT_SECTIONS, CONTENT_URL, SUMMARY_URL } from './audit-fixtures';
import { createFetchMock, errorResponse, jsonResponse, makeUser, page, tokens } from './helpers';
import { navigationState, routerReplace } from './setup';

let net: ReturnType<typeof createFetchMock>;

function renderApp(ui: ReactNode) {
  return render(<AppProviders>{ui}</AppProviders>);
}

function signedInAs(role: UserRole) {
  window.localStorage.setItem(SESSION_HINT_KEY, '1');
  net.on('POST', '/api/v1/admin/auth/refresh', tokens('access'));
  net.on('GET', '/api/v1/admin/auth/me', makeUser(role));
}

beforeEach(() => {
  resetSessionForTests();
  net = createFetchMock();
  vi.stubGlobal('fetch', net.mock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('вход', () => {
  it('после успешного входа переходит на исходную страницу', async () => {
    navigationState.search = 'next=%2Frequests%3Fstatus%3DNEW';
    net.on('POST', '/api/v1/admin/auth/login', tokens('access'));
    net.on('GET', '/api/v1/admin/auth/me', makeUser('MANAGER'));
    const user = userEvent.setup();

    renderApp(<LoginScreen />);
    await user.type(screen.getByLabelText('Email'), 'manager@oinau-pro.kz');
    await user.type(screen.getByLabelText('Пароль'), 'long-enough-password');
    await user.click(screen.getByRole('button', { name: 'Войти' }));

    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith('/requests?status=NEW'));
    const [loginCall] = net.calls('POST', '/api/v1/admin/auth/login');
    expect(JSON.parse(String((loginCall?.[1] as RequestInit).body))).toEqual({
      email: 'manager@oinau-pro.kz',
      password: 'long-enough-password',
    });
  });

  it('показывает сообщение backend при неверном пароле и очищает поле пароля', async () => {
    net.on(
      'POST',
      '/api/v1/admin/auth/login',
      errorResponse(401, 'invalid_credentials', 'Неверный email или пароль'),
    );
    const user = userEvent.setup();

    renderApp(<LoginScreen />);
    await user.type(screen.getByLabelText('Email'), 'admin@oinau-pro.kz');
    await user.type(screen.getByLabelText('Пароль'), 'wrong-password');
    await user.click(screen.getByRole('button', { name: 'Войти' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Неверный email или пароль');
    expect(screen.getByLabelText('Пароль')).toHaveValue('');
  });

  it('объясняет ограничение частоты попыток', async () => {
    net.on(
      'POST',
      '/api/v1/admin/auth/login',
      errorResponse(429, 'rate_limited', 'Слишком много запросов'),
    );
    const user = userEvent.setup();

    renderApp(<LoginScreen />);
    await user.type(screen.getByLabelText('Email'), 'admin@oinau-pro.kz');
    await user.type(screen.getByLabelText('Пароль'), 'x');
    await user.click(screen.getByRole('button', { name: 'Войти' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Слишком много запросов');
  });
});

describe('шлюз сессии', () => {
  it('без сессии отправляет на вход и запоминает, куда шёл сотрудник', async () => {
    navigationState.pathname = '/requests';

    renderApp(
      <AuthGate>
        <p>секретный раздел</p>
      </AuthGate>,
    );

    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith('/login?next=%2Frequests'));
    expect(screen.queryByText('секретный раздел')).not.toBeInTheDocument();
    // Без признака сессии refresh не вызывается вовсе.
    expect(net.calls('POST', '/api/v1/admin/auth/refresh')).toHaveLength(0);
  });

  it('истёкший refresh-токен ведёт на страницу входа', async () => {
    window.localStorage.setItem(SESSION_HINT_KEY, '1');
    net.on(
      'POST',
      '/api/v1/admin/auth/refresh',
      errorResponse(401, 'invalid_refresh_token', 'Сессия недействительна'),
    );

    renderApp(
      <AuthGate>
        <p>секретный раздел</p>
      </AuthGate>,
    );

    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith('/login'));
  });
});

describe('навигация', () => {
  it('менеджеру не показываются категории, контент, пользователи и аудит', async () => {
    signedInAs('MANAGER');
    net.on('GET', '/api/v1/admin/requests', page([]));
    net.on('GET', '/api/v1/admin/products', page([]));
    net.on('GET', '/api/v1/admin/categories', page([]));

    renderApp(
      <PanelLayout>
        <p>контент</p>
      </PanelLayout>,
    );

    const nav = await screen.findByRole('complementary', { name: 'Разделы' });
    const links = within(nav)
      .getAllByRole('link')
      .map((link) => link.textContent);
    // «Импорт / экспорт» менеджеру виден: экспорт и предпросмотр backend
    // разрешает с catalog.read, применение импорта в разделе скрыто.
    expect(links).toEqual(
      expect.arrayContaining(['Заявки', 'Товары', 'Склад', 'Импорт / экспорт']),
    );
    for (const hidden of ['Категории', 'Характеристики', 'Контент', 'Пользователи', 'Аудит']) {
      expect(links).not.toContain(hidden);
    }
    expect(screen.getByText('Менеджер')).toBeInTheDocument();
  });

  it('выход завершает сессию на сервере', async () => {
    signedInAs('ADMIN');
    net.on('POST', '/api/v1/admin/auth/logout', {
      ok: true,
      status: 204,
      json: async () => null,
    } as unknown as Response);
    const user = userEvent.setup();

    renderApp(
      <PanelLayout>
        <p>контент</p>
      </PanelLayout>,
    );

    await user.click(await screen.findByRole('button', { name: /Айгерим Серикова/ }));
    await user.click(screen.getByRole('menuitem', { name: 'Выйти' }));

    await waitFor(() => expect(net.calls('POST', '/api/v1/admin/auth/logout')).toHaveLength(1));
    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith('/login'));
    expect(window.localStorage.getItem(SESSION_HINT_KEY)).toBeNull();
  });
});

describe('дашборд', () => {
  function mockCatalog() {
    net.on('GET', SUMMARY_URL, CATALOG_SUMMARY);
    net.on('GET', '/api/v1/admin/products', page([], 120));
    net.on('GET', CONTENT_URL, CONTENT_SECTIONS);
  }

  it('контент-менеджер не запрашивает заявки, на которые у него нет права', async () => {
    signedInAs('CONTENT_MANAGER');
    mockCatalog();

    renderApp(
      <AuthGate>
        <Dashboard />
      </AuthGate>,
    );

    // Активные товары и категории — из сводки каталога.
    expect(await screen.findByText('96')).toBeInTheDocument();
    // Ссылка «Категории» есть и в карточке-счётчике, и в быстрых переходах.
    const categories = screen
      .getAllByRole('link', { name: /Категории/ })
      .find((link) => link.textContent?.includes('14'));
    expect(categories).toBeDefined();
    expect(screen.queryByText('Новые заявки')).not.toBeInTheDocument();
    expect(net.calls('GET', '/api/v1/admin/requests')).toHaveLength(0);
  });

  it('сводка каталога: карточки без данных и наличие, со ссылками в разделы', async () => {
    signedInAs('ADMIN');
    mockCatalog();
    net.on('GET', '/api/v1/admin/requests', page([]));

    renderApp(
      <AuthGate>
        <Dashboard />
      </AuthGate>,
    );

    const catalog = await screen.findByRole('region', { name: 'Требует внимания' });
    expect(await within(catalog).findByText('9')).toBeInTheDocument();
    expect(within(catalog).getByText('Без изображений')).toBeInTheDocument();
    expect(within(catalog).getByText('11 без готовых')).toBeInTheDocument();
    expect(within(catalog).getByText('5')).toBeInTheDocument();
    expect(within(catalog).getByText('17 по запросу')).toBeInTheDocument();
    expect(within(catalog).getByRole('link', { name: /Черновики/ })).toHaveAttribute(
      'href',
      '/products?status=DRAFT',
    );

    const stock = screen.getByRole('region', { name: 'Наличие на сайте' });
    expect(within(stock).getByRole('link', { name: /В наличии/ })).toHaveAttribute(
      'href',
      '/stock?availability=IN_STOCK',
    );
    expect(within(stock).getByText('70')).toBeInTheDocument();
    // Сводка приходит одним запросом — списков-счётчиков больше нет.
    expect(net.calls('GET', SUMMARY_URL)).toHaveLength(1);
    expect(net.calls('GET', '/api/v1/admin/categories')).toHaveLength(0);
  });

  it('счётчики заявок берутся по статусам backend', async () => {
    signedInAs('MANAGER');
    net.on('GET', '/api/v1/admin/requests', (url: URL) => {
      const status = url.searchParams.get('status');
      return jsonResponse(page([], status === 'NEW' ? 5 : status === 'IN_PROGRESS' ? 3 : 0));
    });
    mockCatalog();

    renderApp(
      <AuthGate>
        <Dashboard />
      </AuthGate>,
    );

    expect(await screen.findByText(/5 новых заявок ждут обработки/)).toBeInTheDocument();
    const statuses = net
      .calls('GET', '/api/v1/admin/requests')
      .map(([url]) => new URL(String(url)).searchParams.get('status'));
    expect(statuses).toEqual(expect.arrayContaining(['NEW', 'IN_PROGRESS']));
    // Менеджеру нечего делать в контенте — раздела и запроса нет.
    expect(screen.queryByText('Разделы сайта')).not.toBeInTheDocument();
    expect(net.calls('GET', CONTENT_URL)).toHaveLength(0);
  });

  it('разделы сайта показываются контент-менеджеру, новые — первыми', async () => {
    signedInAs('CONTENT_MANAGER');
    mockCatalog();

    renderApp(
      <AuthGate>
        <Dashboard />
      </AuthGate>,
    );

    const sections = await screen.findByRole('link', { name: /Контакты/ });
    expect(sections).toHaveAttribute('href', '/content/contacts');
    expect(screen.getAllByText('не заполнен')).toHaveLength(2);
  });

  it('ошибка одного блока не гасит остальные', async () => {
    signedInAs('ADMIN');
    net.on(
      'GET',
      '/api/v1/admin/requests',
      errorResponse(500, 'internal_error', 'Внутренняя ошибка сервера'),
    );
    mockCatalog();

    renderApp(
      <AuthGate>
        <Dashboard />
      </AuthGate>,
    );

    expect(await screen.findByText('96')).toBeInTheDocument();
    expect(await screen.findAllByText('Не удалось загрузить данные')).not.toHaveLength(0);
  });

  it('отказ сводки каталога показывает ошибку с повтором, остальное остаётся', async () => {
    signedInAs('ADMIN');
    net.on('GET', SUMMARY_URL, errorResponse(500, 'internal_error', 'Внутренняя ошибка сервера'));
    net.on('GET', '/api/v1/admin/products', page([], 0));
    net.on('GET', '/api/v1/admin/requests', page([], 0));
    net.on('GET', CONTENT_URL, CONTENT_SECTIONS);

    renderApp(
      <AuthGate>
        <Dashboard />
      </AuthGate>,
    );

    const catalogCard = (await screen.findAllByText('Не удалось загрузить данные'))[0];
    expect(catalogCard).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Повторить' }).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Последние заявки').length).toBeGreaterThan(0);
  });
});

describe('подтверждение опасных действий', () => {
  function DeleteButton({ onResult }: { onResult: (value: boolean) => void }) {
    const confirm = useConfirm();
    return (
      <button
        type="button"
        onClick={async () =>
          onResult(await confirm({ title: 'Удалить товар?', confirmLabel: 'Удалить' }))
        }
      >
        удалить
      </button>
    );
  }

  it('возвращает true только по явному подтверждению; Esc — отмена', async () => {
    const onResult = vi.fn();
    const user = userEvent.setup();
    renderApp(<DeleteButton onResult={onResult} />);

    await user.click(screen.getByRole('button', { name: 'удалить' }));
    expect(screen.getByRole('dialog', { name: 'Удалить товар?' })).toBeInTheDocument();
    // Фокус на «Отмена»: случайный Enter ничего не удаляет.
    expect(screen.getByRole('button', { name: 'Отмена' })).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(onResult).toHaveBeenLastCalledWith(false);

    await user.click(screen.getByRole('button', { name: 'удалить' }));
    await user.click(screen.getByRole('button', { name: 'Удалить' }));
    expect(onResult).toHaveBeenLastCalledWith(true);
  });
});
