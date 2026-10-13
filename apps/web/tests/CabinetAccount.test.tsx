/**
 * Разделы кабинета: доступ только после входа, меню, заявки, профиль,
 * проекты, уведомления, избранное и связь с витриной (шапка, заявка).
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@oinau/api-client';

import { CabinetDashboard } from '@/components/cabinet/CabinetDashboard';
import { CabinetFavorites } from '@/components/cabinet/CabinetFavorites';
import { CabinetShell } from '@/components/cabinet/CabinetShell';
import { NotificationsList } from '@/components/cabinet/NotificationsList';
import { ProfileForm } from '@/components/cabinet/ProfileForm';
import { ProjectDetailView } from '@/components/cabinet/ProjectDetailView';
import { ProjectsList } from '@/components/cabinet/ProjectsList';
import { RequestDetailView } from '@/components/cabinet/RequestDetailView';
import { RequestsList } from '@/components/cabinet/RequestsList';
import { ProductCard } from '@/components/catalog/ProductCard';
import { Providers } from '@/components/layout/Providers';
import { SiteHeader } from '@/components/layout/SiteHeader';
import {
  makeNotification,
  makeProfile,
  makeProject,
  makeProjectDetail,
  makeRequestDetail,
  makeRequestItem,
  page,
} from './cabinet-factories';
import {
  authApi,
  catalogApi,
  customerApi,
  regionsApi,
  resetCabinetMocks,
  signIn,
} from './cabinet-mocks';
import { makeCategories, makeProduct, makeProductDetail } from './factories';
import { navigationState, routerPush, routerReplace } from './setup';

vi.mock('@/lib/api/customer', async () => ({
  ...(await import('./cabinet-mocks')).customerApi,
  CABINET_PAGE_SIZE: 20,
  MAX_PAGE_SIZE: 60,
}));
vi.mock('@/lib/api/customer-auth', async () => ({ ...(await import('./cabinet-mocks')).authApi }));
vi.mock('@/lib/api/requests', async () => ({
  ...(await import('./cabinet-mocks')).regionsApi,
  newIdempotencyKey: () => 'test-key',
}));
vi.mock('@/lib/api/catalog', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api/catalog')>()),
  ...(await import('./cabinet-mocks')).catalogApi,
}));
vi.mock('@/lib/cabinet/session', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/cabinet/session')>();
  const { sessionState: state } = await import('./cabinet-mocks');
  return {
    ...actual,
    hasSessionHint: () => state.hint,
    getAccessToken: async () => state.token,
  };
});

function renderUi(ui: React.ReactNode) {
  return render(<Providers>{ui}</Providers>);
}

function renderCabinet(ui: React.ReactNode, pathname = '/cabinet') {
  navigationState.pathname = pathname;
  return renderUi(<CabinetShell>{ui}</CabinetShell>);
}

beforeEach(() => {
  resetCabinetMocks();
});

// ================================================================ доступ

describe('доступ к кабинету', () => {
  it('гостя отправляет на вход с адресом возврата и не запрашивает данные', async () => {
    renderCabinet(<RequestsList page={1} />, '/cabinet/projects');

    await waitFor(() =>
      expect(routerReplace).toHaveBeenCalledWith('/cabinet/login?next=%2Fcabinet%2Fprojects'),
    );
    expect(customerApi.fetchProfile).not.toHaveBeenCalled();
    expect(customerApi.fetchCustomerRequests).not.toHaveBeenCalled();
    expect(screen.queryByRole('navigation', { name: 'Разделы кабинета' })).not.toBeInTheDocument();
  });

  it('истёкшая сессия (refresh отклонён) тоже ведёт на вход', async () => {
    signIn();
    customerApi.fetchProfile.mockRejectedValue(new ApiError(401, 'unauthenticated', 'x'));
    renderCabinet(<div>секрет</div>, '/cabinet/profile');

    await waitFor(() =>
      expect(routerReplace).toHaveBeenCalledWith('/cabinet/login?next=%2Fcabinet%2Fprofile'),
    );
    expect(screen.queryByText('секрет')).not.toBeInTheDocument();
  });

  it('сбой сети — сообщение с повтором, а не выход из кабинета', async () => {
    const user = userEvent.setup();
    signIn();
    customerApi.fetchProfile.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    renderCabinet(<div>Содержимое</div>);

    expect(await screen.findByText('Кабинет временно недоступен')).toBeInTheDocument();
    expect(routerReplace).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(await screen.findByText('Содержимое')).toBeInTheDocument();
  });

  it('меню показывает клиента, активный раздел и непрочитанные', async () => {
    signIn();
    customerApi.fetchUnreadCount.mockResolvedValue({ unread: 3 });
    renderCabinet(<div>Заявки</div>, '/cabinet/requests/R-2026-000042');

    const nav = await screen.findByRole('navigation', { name: 'Разделы кабинета' });
    expect(screen.getByText('Park Group')).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: /Заявки/ })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(within(nav).getByRole('link', { name: /Обзор/ })).not.toHaveAttribute('aria-current');
    expect(await within(nav).findByLabelText('непрочитанных: 3')).toBeInTheDocument();
  });

  it('мобильная кнопка раскрывает меню разделов', async () => {
    const user = userEvent.setup();
    signIn();
    renderCabinet(<div />, '/cabinet/projects');

    const toggle = await screen.findByRole('button', { name: /Проекты/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
  });

  it('выход очищает сессию и ведёт на форму входа', async () => {
    const user = userEvent.setup();
    signIn();
    renderCabinet(<div />);

    await user.click(await screen.findByRole('button', { name: 'Выйти' }));

    expect(authApi.logoutCustomer).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith('/cabinet/login'));
    expect(await screen.findByText('Вы вышли из кабинета')).toBeInTheDocument();
  });
});

// ================================================================ обзор

describe('главная кабинета', () => {
  it('приветствие, сводка и последние заявки', async () => {
    signIn();
    customerApi.fetchCustomerRequests.mockResolvedValue(page([makeRequestItem()], { total: 7 }));
    customerApi.fetchProjects.mockResolvedValue(page([], { total: 2 }));
    customerApi.fetchUnreadCount.mockResolvedValue({ unread: 1 });
    renderCabinet(<CabinetDashboard />);

    expect(await screen.findByRole('heading', { level: 1, name: /Айгерим/ })).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: /R-2026-000042/ })).toHaveAttribute(
      'href',
      '/cabinet/requests/R-2026-000042',
    );
    expect(await screen.findByRole('link', { name: /^Заявки\s*7$/ })).toHaveAttribute(
      'href',
      '/cabinet/requests',
    );
    expect(screen.getByRole('link', { name: /Новый проект/ })).toHaveAttribute(
      'href',
      '/cabinet/projects?create=1',
    );
  });
});

// ================================================================ заявки

describe('заявки', () => {
  it('таблица: номер, дата, статус, позиции, сумма и страницы', async () => {
    signIn();
    customerApi.fetchCustomerRequests.mockResolvedValue(
      page(
        [
          makeRequestItem(),
          makeRequestItem({ number: 'R-2026-000041', status: 'CANCELLED', total_estimate: null }),
        ],
        {
          page: 2,
          pages: 3,
          total: 45,
        },
      ),
    );
    renderCabinet(<RequestsList page={2} />, '/cabinet/requests');

    const table = await screen.findByRole('table');
    const rows = within(table).getAllByRole('row');
    expect(rows).toHaveLength(3);
    expect(within(rows[1]!).getByText('В работе')).toBeInTheDocument();
    expect(within(rows[1]!).getByText(/125\s000 ₸/)).toBeInTheDocument();
    expect(within(rows[2]!).getByText('Отменена')).toBeInTheDocument();
    expect(within(rows[2]!).getByText('По запросу')).toBeInTheDocument();
    expect(customerApi.fetchCustomerRequests).toHaveBeenCalledWith({ page: 2, pageSize: 20 });

    const pagination = screen.getByRole('navigation', { name: 'Страницы списка' });
    expect(within(pagination).getByRole('link', { name: 'Страница 1' })).toHaveAttribute(
      'href',
      '/cabinet/requests',
    );
    expect(within(pagination).getByRole('link', { name: 'Страница 3' })).toHaveAttribute(
      'href',
      '/cabinet/requests?page=3',
    );
    expect(within(pagination).getByText(/Показано 2 из 45/)).toBeInTheDocument();
  });

  it('пустой список и ошибка с повтором', async () => {
    const user = userEvent.setup();
    signIn();
    const { unmount } = renderCabinet(<RequestsList page={1} />, '/cabinet/requests');
    expect(await screen.findByText('Заявок пока нет')).toBeInTheDocument();
    unmount();

    customerApi.fetchCustomerRequests
      .mockRejectedValueOnce(new ApiError(500, 'internal_error', 'Внутренняя ошибка'))
      .mockResolvedValueOnce(page([makeRequestItem()]));
    renderCabinet(<RequestsList page={1} />, '/cabinet/requests');

    expect(await screen.findByText('Не удалось загрузить заявки')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(await screen.findByRole('link', { name: 'R-2026-000042' })).toBeInTheDocument();
  });

  it('карточка заявки: товары, итог, ответы менеджера и история', async () => {
    signIn();
    customerApi.fetchCustomerRequest.mockResolvedValue(
      makeRequestDetail({ project: { uuid: makeProject().uuid, name: 'Площадка ЖК «Алатау»' } }),
    );
    renderCabinet(<RequestDetailView number="R-2026-000042" />, '/cabinet/requests/R-2026-000042');

    expect(
      await screen.findByRole('heading', { level: 1, name: 'R-2026-000042' }),
    ).toBeInTheDocument();
    expect(customerApi.fetchCustomerRequest).toHaveBeenCalledWith('R-2026-000042');
    expect(screen.getByText('Канат армированный Ø16 мм')).toBeInTheDocument();
    expect(screen.getByText('RP-016')).toBeInTheDocument();
    expect(screen.getByText('50 м')).toBeInTheDocument();
    expect(screen.getByText('Счёт отправлен на почту')).toBeInTheDocument();
    expect(screen.getByText('Нужна доставка до 20 сентября')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Площадка ЖК «Алатау»' })).toHaveAttribute(
      'href',
      `/cabinet/projects/${makeProject().uuid}`,
    );
  });

  it('выводит только комментарии для клиента — лишние поля ответа игнорируются', async () => {
    signIn();
    const detail = {
      ...makeRequestDetail({ comments: [] }),
      internal_comments: [{ body: 'СЛУЖЕБНО: клиент тянет с оплатой' }],
      manager_note: 'СЛУЖЕБНО: скидка 5%',
    };
    customerApi.fetchCustomerRequest.mockResolvedValue(detail);
    renderCabinet(<RequestDetailView number="R-2026-000042" />, '/cabinet/requests/R-2026-000042');

    expect(
      await screen.findByText('Пока ответов нет — менеджер свяжется с вами.'),
    ).toBeInTheDocument();
    expect(screen.queryByText(/СЛУЖЕБНО/)).not.toBeInTheDocument();
  });

  it('чужая или несуществующая заявка — «не найдена»', async () => {
    signIn();
    customerApi.fetchCustomerRequest.mockRejectedValue(
      new ApiError(404, 'request_not_found', 'Заявка не найдена'),
    );
    renderCabinet(<RequestDetailView number="R-2026-999999" />, '/cabinet/requests/R-2026-999999');

    expect(await screen.findByRole('link', { name: 'К списку заявок' })).toBeInTheDocument();
    expect(screen.getByText('Заявка не найдена')).toBeInTheDocument();
  });
});

// ================================================================ профиль

describe('профиль', () => {
  it('email только показывается, отправляются лишь изменённые поля', async () => {
    const user = userEvent.setup();
    signIn();
    customerApi.updateProfile.mockImplementation(async (changes: Record<string, unknown>) =>
      makeProfile({ ...(changes as object), company_name: 'Park Group Almaty' }),
    );
    renderCabinet(<ProfileForm />, '/cabinet/profile');

    const company = await screen.findByLabelText(/Компания/);
    expect(screen.queryByDisplayValue('buyer@park-group.kz')).not.toBeInTheDocument();
    expect(screen.getAllByText('buyer@park-group.kz').length).toBeGreaterThan(0);

    const save = screen.getByRole('button', { name: 'Сохранить изменения' });
    expect(save).toBeDisabled();

    await user.clear(company);
    await user.type(company, 'Park Group Almaty');
    await user.click(save);

    await waitFor(() =>
      expect(customerApi.updateProfile).toHaveBeenCalledWith({ company_name: 'Park Group Almaty' }),
    );
    expect(await screen.findByText('Профиль сохранён')).toBeInTheDocument();
    const payload = customerApi.updateProfile.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(payload).not.toHaveProperty('email');
  });

  it('регион не запрашивается: поля нет и справочник не грузится', async () => {
    signIn();
    renderCabinet(<ProfileForm />, '/cabinet/profile');

    expect(await screen.findByLabelText(/Компания/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Регион/)).not.toBeInTheDocument();
    expect(regionsApi.fetchRegions).not.toHaveBeenCalled();
  });

  it('проверяет телефон до отправки', async () => {
    const user = userEvent.setup();
    signIn();
    renderCabinet(<ProfileForm />, '/cabinet/profile');

    const phone = await screen.findByLabelText(/Телефон/);
    await user.clear(phone);
    await user.type(phone, '12');
    await user.click(screen.getByRole('button', { name: 'Сохранить изменения' }));

    expect(screen.getByText('В номере должно быть от 5 до 15 цифр')).toBeInTheDocument();
    expect(customerApi.updateProfile).not.toHaveBeenCalled();
  });
});

// ================================================================ проекты

describe('проекты', () => {
  it('создание проекта ведёт в его карточку', async () => {
    const user = userEvent.setup();
    signIn();
    customerApi.createProject.mockResolvedValue(makeProjectDetail());
    renderCabinet(<ProjectsList page={1} />, '/cabinet/projects');

    await user.click(await screen.findByRole('button', { name: 'Создать первый проект' }));
    const dialog = screen.getByRole('dialog', { name: 'Новый проект' });
    await user.click(within(dialog).getByRole('button', { name: 'Создать проект' }));
    expect(within(dialog).getByText('Назовите проект')).toBeInTheDocument();

    await user.type(within(dialog).getByLabelText(/Название/), 'Площадка ЖК «Алатау»');
    await user.click(within(dialog).getByRole('button', { name: 'Создать проект' }));

    await waitFor(() =>
      expect(customerApi.createProject).toHaveBeenCalledWith({
        name: 'Площадка ЖК «Алатау»',
        description: null,
        region_id: null,
        status: 'PLANNING',
      }),
    );
    expect(routerPush).toHaveBeenCalledWith(`/cabinet/projects/${makeProject().uuid}`);
  });

  it('удаление только после подтверждения', async () => {
    const user = userEvent.setup();
    signIn();
    customerApi.fetchProjects.mockResolvedValue(page([makeProject()]));
    customerApi.deleteProject.mockResolvedValue(undefined);
    renderCabinet(<ProjectsList page={1} />, '/cabinet/projects');

    await user.click(
      await screen.findByRole('button', { name: 'Удалить проект «Площадка ЖК «Алатау»»' }),
    );
    let dialog = screen.getByRole('dialog', { name: 'Удалить проект?' });
    await user.click(within(dialog).getByRole('button', { name: 'Отмена' }));
    expect(customerApi.deleteProject).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Удалить проект «Площадка ЖК «Алатау»»' }));
    dialog = screen.getByRole('dialog', { name: 'Удалить проект?' });
    await user.click(within(dialog).getByRole('button', { name: 'Удалить проект' }));

    await waitFor(() => expect(customerApi.deleteProject).toHaveBeenCalledWith(makeProject().uuid));
    expect(await screen.findByText('Проект «Площадка ЖК «Алатау»» удалён')).toBeInTheDocument();
  });

  it('Escape закрывает диалог подтверждения', async () => {
    const user = userEvent.setup();
    signIn();
    customerApi.fetchProjects.mockResolvedValue(page([makeProject()]));
    renderCabinet(<ProjectsList page={1} />, '/cabinet/projects');

    await user.click(
      await screen.findByRole('button', { name: 'Удалить проект «Площадка ЖК «Алатау»»' }),
    );
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('карточка проекта: добавление и удаление позиции', async () => {
    const user = userEvent.setup();
    signIn();
    const uuid = makeProject().uuid;
    customerApi.fetchProject.mockResolvedValue(makeProjectDetail());
    customerApi.addProjectItem.mockResolvedValue(
      makeProjectDetail({
        items_count: 2,
        items: [
          ...makeProjectDetail().items,
          {
            sku: 'KR-100',
            name: 'Карабин стальной',
            slug: null,
            is_available: false,
            quantity: null,
            note: 'Под замену',
            added_at: '2026-09-13T08:00:00Z',
          },
        ],
      }),
    );
    customerApi.removeProjectItem.mockResolvedValue(undefined);
    renderCabinet(<ProjectDetailView uuid={uuid} />, `/cabinet/projects/${uuid}`);

    expect(await screen.findByRole('link', { name: 'Канат армированный Ø16 мм' })).toHaveAttribute(
      'href',
      '/product/kanat-armirovannyj-16-mm',
    );

    await user.type(screen.getByLabelText(/Артикул/), 'KR-100');
    await user.type(screen.getByLabelText(/Количество/), '2,5');
    await user.type(screen.getByLabelText(/Заметка/), 'Под замену');
    await user.click(screen.getByRole('button', { name: 'Добавить' }));

    await waitFor(() =>
      expect(customerApi.addProjectItem).toHaveBeenCalledWith(uuid, {
        sku: 'KR-100',
        quantity: '2.5',
        note: 'Под замену',
      }),
    );
    expect(await screen.findByText('Карабин стальной')).toBeInTheDocument();
    expect(screen.getByText('Недоступен')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Убрать из проекта: Карабин стальной' }));
    await waitFor(() => expect(customerApi.removeProjectItem).toHaveBeenCalledWith(uuid, 'KR-100'));
    await waitFor(() => expect(screen.queryByText('Карабин стальной')).not.toBeInTheDocument());
  });

  it('недоступный артикул — ошибка у поля', async () => {
    const user = userEvent.setup();
    signIn();
    customerApi.fetchProject.mockResolvedValue(makeProjectDetail());
    customerApi.addProjectItem.mockRejectedValue(
      new ApiError(422, 'product_unavailable', 'Товар недоступен'),
    );
    renderCabinet(<ProjectDetailView uuid={makeProject().uuid} />, '/cabinet/projects/x');

    await user.type(await screen.findByLabelText(/Артикул/), 'NOPE-1');
    await user.click(screen.getByRole('button', { name: 'Добавить' }));

    expect(
      await screen.findByText('Товар с таким артикулом не найден или недоступен'),
    ).toBeInTheDocument();
  });
});

// ================================================================ уведомления

describe('уведомления', () => {
  it('отметка прочитанным обновляет строку и счётчик', async () => {
    const user = userEvent.setup();
    signIn();
    const notification = makeNotification();
    customerApi.fetchUnreadCount.mockResolvedValue({ unread: 1 });
    customerApi.fetchNotifications.mockResolvedValue(page([notification]));
    customerApi.markNotificationRead.mockResolvedValue({
      ...notification,
      is_read: true,
      read_at: '2026-09-13T10:00:00Z',
    });
    renderCabinet(<NotificationsList page={1} unreadOnly={false} />, '/cabinet/notifications');

    expect(await screen.findByText('Непрочитанных: 1')).toBeInTheDocument();
    expect(
      await screen.findByRole('link', { name: 'Открыть заявку R-2026-000042' }),
    ).toHaveAttribute('href', '/cabinet/requests/R-2026-000042');

    await user.click(screen.getByRole('button', { name: 'Отметить прочитанным: Заявка в работе' }));

    expect(customerApi.markNotificationRead).toHaveBeenCalledWith(notification.uuid);
    expect(await screen.findByText('Новых уведомлений нет')).toBeInTheDocument();
  });

  it('«отметить все» и фильтр непрочитанных', async () => {
    const user = userEvent.setup();
    signIn();
    customerApi.fetchUnreadCount.mockResolvedValue({ unread: 2 });
    customerApi.fetchNotifications.mockResolvedValue(page([makeNotification()]));
    customerApi.markAllNotificationsRead.mockResolvedValue({ unread: 0 });
    renderCabinet(<NotificationsList page={1} unreadOnly />, '/cabinet/notifications');

    const filter = await screen.findByRole('group', { name: 'Фильтр уведомлений' });
    expect(within(filter).getByRole('link', { name: /Непрочитанные/ })).toHaveAttribute(
      'aria-current',
      'page',
    );
    await waitFor(() =>
      expect(customerApi.fetchNotifications).toHaveBeenCalledWith({
        page: 1,
        pageSize: 20,
        unread: true,
      }),
    );

    const markAll = screen.getByRole('button', { name: 'Отметить все прочитанными' });
    await waitFor(() => expect(markAll).toBeEnabled());
    await user.click(markAll);

    expect(customerApi.markAllNotificationsRead).toHaveBeenCalledTimes(1);
    expect(await screen.findByText('Все уведомления отмечены прочитанными')).toBeInTheDocument();
  });
});

// ================================================================ избранное

describe('избранное в аккаунте', () => {
  it('рисует карточки каталога и убирает позицию через API', async () => {
    const user = userEvent.setup();
    signIn();
    customerApi.fetchAllFavoriteSkus.mockResolvedValue(['RP-016']);
    customerApi.fetchFavorites.mockResolvedValue(
      page([
        {
          sku: 'RP-016',
          slug: 'kanat-armirovannyj-16-mm',
          name: 'Канат армированный Ø16 мм',
          unit: 'm',
          added_at: '2026-09-10T08:00:00Z',
        },
      ]),
    );
    catalogApi.fetchProduct.mockResolvedValue(makeProductDetail());
    customerApi.removeFavorite.mockResolvedValue(undefined);
    renderCabinet(<CabinetFavorites page={1} />, '/cabinet/favorites');

    expect(await screen.findByRole('link', { name: 'Канат армированный Ø16 мм' })).toHaveAttribute(
      'href',
      '/product/kanat-armirovannyj-16-mm',
    );
    expect(catalogApi.fetchProduct).toHaveBeenCalledWith('kanat-armirovannyj-16-mm');

    // Кнопка под карточкой (сердечко на карточке делает то же самое).
    await user.click(await screen.findByText('Убрать из избранного', { selector: 'button' }));

    await waitFor(() => expect(customerApi.removeFavorite).toHaveBeenCalledWith('RP-016'));
    expect(await screen.findByText('В избранном пока пусто')).toBeInTheDocument();
  });

  it('сердечко в каталоге у вошедшего клиента пишет в аккаунт, а не в localStorage', async () => {
    const user = userEvent.setup();
    signIn();
    customerApi.addFavorite.mockResolvedValue({});
    renderUi(<ProductCard product={makeProduct()} />);

    const heart = await screen.findByRole('button', { name: /В избранное/ });
    await waitFor(() => expect(customerApi.fetchAllFavoriteSkus).toHaveBeenCalled());
    await user.click(heart);

    await waitFor(() => expect(customerApi.addFavorite).toHaveBeenCalledWith('RP-016'));
    expect(screen.getByRole('button', { name: /Убрать из избранного/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(window.localStorage.getItem('oinau.favorites.v1') ?? '[]').not.toContain('RP-016');
  });

  it('при входе гостевое избранное переносится в аккаунт', async () => {
    window.localStorage.setItem(
      'oinau.favorites.v1',
      JSON.stringify([
        {
          sku: 'RP-016',
          slug: 'kanat',
          name: 'Канат',
          unit: 'm',
          priceLabel: '',
          availabilityLabel: '',
        },
      ]),
    );
    signIn();
    customerApi.addFavorite.mockResolvedValue({});
    customerApi.fetchAllFavoriteSkus.mockResolvedValue(['RP-016']);
    renderUi(<ProductCard product={makeProduct()} />);

    await waitFor(() => expect(customerApi.addFavorite).toHaveBeenCalledWith('RP-016'));
    await waitFor(() =>
      expect(window.localStorage.getItem('oinau.favorites.v1')).not.toContain('RP-016'),
    );
    expect(await screen.findByRole('button', { name: /Убрать из избранного/ })).toBeInTheDocument();
  });
});

// ================================================================ витрина

describe('связь с витриной', () => {
  it('заявка вошедшего клиента уходит через кабинет с контактами из профиля', async () => {
    const user = userEvent.setup();
    signIn();
    customerApi.submitCustomerRequest.mockResolvedValue({
      number: 'R-2026-000150',
      created_at: '2026-09-13T10:00:00Z',
      currency: 'KZT',
      total_estimate: '7000.00',
      items: [],
    });
    renderUi(
      <>
        <SiteHeader categories={makeCategories()} />
        <ProductCard product={makeProduct()} />
      </>,
    );

    await screen.findByRole('link', { name: 'Кабинет' });
    await user.click(screen.getByRole('button', { name: 'Добавить в корзину' }));
    await user.click(screen.getByRole('button', { name: /^Корзина/ }));
    const dialog = screen.getByRole('dialog', { name: 'Корзина' });

    expect(within(dialog).getByText(/Контакты взяты из профиля кабинета/)).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/Имя/)).toHaveValue('Айгерим');
    expect(within(dialog).getByLabelText(/Телефон/)).toHaveValue('+77010000000');

    await user.click(within(dialog).getByRole('button', { name: 'Отправить заявку' }));

    await waitFor(() => expect(customerApi.submitCustomerRequest).toHaveBeenCalledTimes(1));
    const [payload, key] = customerApi.submitCustomerRequest.mock.calls[0]!;
    expect(payload).toMatchObject({
      name: 'Айгерим',
      phone: '+77010000000',
      email: 'buyer@park-group.kz',
      company: 'Park Group',
      items: [{ sku: 'RP-016', quantity: '1' }],
    });
    expect(key).toBe('test-key');
  });

  it('шапка: гостю «Войти», вошедшему — «Кабинет» и избранное в кабинете', async () => {
    const { unmount } = renderUi(<SiteHeader categories={makeCategories()} />);
    expect(screen.getByRole('link', { name: 'Войти' })).toHaveAttribute('href', '/cabinet/login');
    unmount();

    signIn();
    customerApi.fetchUnreadCount.mockResolvedValue({ unread: 2 });
    renderUi(<SiteHeader categories={makeCategories()} />);

    expect(
      await screen.findByRole('link', { name: 'Кабинет: непрочитанных уведомлений 2' }),
    ).toHaveAttribute('href', '/cabinet');
    await waitFor(() =>
      expect(screen.getByRole('link', { name: 'Избранное' })).toHaveAttribute(
        'href',
        '/cabinet/favorites',
      ),
    );
  });
});
