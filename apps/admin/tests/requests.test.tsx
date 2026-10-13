/**
 * Раздел заявок: список, фильтры, страницы, карточка, статусы,
 * комментарии, права и состояния экрана.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import RequestsPage from '@/app/(panel)/requests/page';
import { AppProviders } from '@/components/AppProviders';
import { RequestDetailScreen } from '@/components/requests/RequestDetailScreen';
import { RequestsList } from '@/components/requests/RequestsList';
import { AuthGate, RequirePermission } from '@/components/session/AuthGate';
import type { RequestDetail, UserRole } from '@/lib/api/types';
import { Permission } from '@/lib/auth/permissions';
import { resetSessionForTests } from '@/lib/auth/session';
import { dayEnd, dayStart, filtersFromParams, needsStatusConfirm } from '@/lib/requests';

import {
  authHeader,
  createFetchMock,
  errorResponse,
  fileResponse,
  jsonResponse,
  makeRequestDetail,
  makeRequestListItem,
  page,
  signInAs,
} from './helpers';
import { navigationState, routerPush, routerReplace } from './setup';

const LIST = '/api/v1/admin/requests';
const DETAIL = '/api/v1/admin/requests/7';
// Testing Library схлопывает неразрывные пробелы в обычные; сами NBSP
// проверяются в decimal.test.ts.
const NBSP = ' ';

let net: ReturnType<typeof createFetchMock>;

function renderInPanel(ui: ReactNode) {
  return render(
    <AppProviders>
      <AuthGate>{ui}</AuthGate>
    </AppProviders>,
  );
}

function listCalls() {
  return net.calls('GET', LIST).map(([url]) => new URL(String(url)).searchParams);
}

function lastListParams() {
  const calls = listCalls();
  return calls[calls.length - 1];
}

async function openList(role: UserRole = 'MANAGER') {
  signInAs(net, role);
  net.on('GET', '/api/v1/public/regions', [{ id: 1, code: 'almaty', name: 'Алматы' }]);
  renderInPanel(<RequestsList />);
  return screen.findByRole('table', { name: 'Заявки' });
}

async function openDetail(role: UserRole = 'MANAGER', detail: RequestDetail = makeRequestDetail()) {
  signInAs(net, role);
  net.on('GET', DETAIL, detail);
  renderInPanel(
    <RequirePermission all={[Permission.REQUEST_READ]}>
      <RequestDetailScreen id={7} />
    </RequirePermission>,
  );
  await screen.findByRole('heading', { name: detail.number });
}

beforeEach(() => {
  resetSessionForTests();
  net = createFetchMock();
  vi.stubGlobal('fetch', net.mock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ================================================================ список
describe('список заявок', () => {
  it('показывает заявки плотной таблицей', async () => {
    net.on(
      'GET',
      LIST,
      page([
        makeRequestListItem(),
        makeRequestListItem({
          id: 2,
          number: 'R-2026-000002',
          kind: 'GENERAL',
          items_count: 0,
          total_estimate: null,
          status: 'QUOTE_SENT',
          company: null,
        }),
      ]),
    );

    const table = await openList();
    await within(table).findByRole('link', { name: 'R-2026-000002' });
    const rows = within(table).getAllByRole('row');

    expect(rows).toHaveLength(3);
    const first = within(rows[1] as HTMLElement);
    expect(first.getByRole('link', { name: 'R-2026-000001' })).toHaveAttribute(
      'href',
      '/requests/1',
    );
    expect(first.getByText('Нурлан Бекенов')).toBeInTheDocument();
    expect(first.getByText('+7 777 210 44 18')).toBeInTheDocument();
    expect(first.getByText('2 позиции')).toBeInTheDocument();
    expect(first.getByText(`520${NBSP}200${NBSP}₸`)).toBeInTheDocument();
    expect(first.getByText('Новая')).toBeInTheDocument();
    const second = within(rows[2] as HTMLElement);
    expect(second.getByText('Общий запрос')).toBeInTheDocument();
    expect(second.getByText('КП отправлено')).toBeInTheDocument();

    const params = lastListParams();
    expect(params?.get('sort')).toBe('newest');
    expect(params?.get('page_size')).toBe('20');
    expect(params?.get('page')).toBe('1');
  });

  it('открывает карточку по клику на строку', async () => {
    net.on('GET', LIST, page([makeRequestListItem({ id: 42 })]));
    const user = userEvent.setup();

    const table = await openList();
    await user.click(await within(table).findByText('Нурлан Бекенов'));

    expect(routerPush).toHaveBeenCalledWith('/requests/42');
  });

  it('берёт фильтр статуса из адреса (ссылка с дашборда)', async () => {
    navigationState.pathname = '/requests';
    navigationState.search = 'status=NEW';
    net.on('GET', LIST, page([makeRequestListItem()]));

    await openList();

    await waitFor(() => expect(lastListParams()?.get('status')).toBe('NEW'));
    expect(screen.getByLabelText('Статус')).toHaveValue('NEW');
  });

  it('фильтр по статусу — значения backend, сброс на первую страницу, запись в адрес', async () => {
    navigationState.pathname = '/requests';
    navigationState.search = 'page=3';
    net.on('GET', LIST, page([makeRequestListItem()], 100));
    const user = userEvent.setup();

    await openList();
    const select = screen.getByLabelText('Статус');
    const values = within(select)
      .getAllByRole('option')
      .map((option) => option.getAttribute('value'));
    expect(values).toEqual([
      '',
      'NEW',
      'IN_PROGRESS',
      'WAITING_CLIENT',
      'QUOTE_SENT',
      'APPROVED',
      'COMPLETED',
      'CANCELLED',
      'SPAM',
    ]);

    await user.selectOptions(select, 'IN_PROGRESS');

    await waitFor(() => expect(lastListParams()?.get('status')).toBe('IN_PROGRESS'));
    expect(lastListParams()?.get('page')).toBe('1');
    expect(routerReplace).toHaveBeenLastCalledWith('/requests?status=IN_PROGRESS', {
      scroll: false,
    });
  });

  it('поиск уходит на backend одним запросом после паузы ввода', async () => {
    net.on('GET', LIST, page([makeRequestListItem()]));
    const user = userEvent.setup();

    await openList();
    await waitFor(() => expect(listCalls()).toHaveLength(1));
    await user.type(screen.getByLabelText('Поиск'), '+7 777');

    await waitFor(() => expect(lastListParams()?.get('search')).toBe('+7 777'));
    expect(listCalls().filter((params) => params.has('search'))).toHaveLength(1);
  });

  it('период фильтра переводится в границы суток по Алматы', async () => {
    navigationState.search = 'from=2026-09-01&to=2026-09-14';
    net.on('GET', LIST, page([]));

    await openList();

    await waitFor(() =>
      expect(lastListParams()?.get('created_from')).toBe('2026-09-01T00:00:00+05:00'),
    );
    expect(lastListParams()?.get('created_to')).toBe('2026-09-15T00:00:00+05:00');
  });

  it('перевёрнутый период не отправляется на backend', async () => {
    navigationState.search = 'from=2026-09-14&to=2026-09-01';
    signInAs(net, 'MANAGER');
    net.on('GET', LIST, page([]));
    net.on('GET', '/api/v1/public/regions', []);

    renderInPanel(<RequestsList />);

    expect(await screen.findByText('Дата «с» позже даты «по»')).toBeInTheDocument();
    expect(listCalls()).toHaveLength(0);
  });

  it('листает страницы', async () => {
    navigationState.pathname = '/requests';
    net.on('GET', LIST, (url: URL) =>
      jsonResponse({
        ...page([makeRequestListItem({ id: Number(url.searchParams.get('page')) })], 45),
        page: Number(url.searchParams.get('page')),
        page_size: 20,
        pages: 3,
      }),
    );
    const user = userEvent.setup();

    await openList();
    expect(await screen.findByText('1–20')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Следующая страница' }));

    await waitFor(() => expect(lastListParams()?.get('page')).toBe('2'));
    expect(routerReplace).toHaveBeenLastCalledWith('/requests?page=2', { scroll: false });
    expect(await screen.findByText('21–40')).toBeInTheDocument();
  });

  it('пустой список и пустой результат фильтра различаются', async () => {
    net.on('GET', LIST, page([]));
    const table = await openList();
    expect(await within(table).findByText('Заявок пока нет')).toBeInTheDocument();
  });

  it('пустой результат по фильтру предлагает сбросить условия', async () => {
    navigationState.search = 'status=SPAM';
    net.on('GET', LIST, page([]));
    const table = await openList();
    expect(await within(table).findByText('Ничего не найдено')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Сбросить' })).toBeInTheDocument();
  });

  it('показывает skeleton, пока список грузится', async () => {
    net.on('GET', LIST, () => new Promise<Response>(() => undefined));
    const table = await openList();
    expect(table).toHaveAttribute('aria-busy', 'true');
  });

  it('ошибка сервера — сообщение и повтор', async () => {
    let calls = 0;
    net.on('GET', LIST, () => {
      calls += 1;
      return calls === 1
        ? errorResponse(500, 'internal_error', 'Внутренняя ошибка сервера')
        : jsonResponse(page([makeRequestListItem()]));
    });
    const user = userEvent.setup();

    const table = await openList();
    await user.click(await within(table).findByRole('button', { name: 'Повторить' }));

    expect(await within(table).findByText('Нурлан Бекенов')).toBeInTheDocument();
  });

  it('403 от backend показывает «Нет доступа», а не падение', async () => {
    net.on('GET', LIST, errorResponse(403, 'permission_denied', 'Недостаточно прав'));
    const table = await openList();
    expect(await within(table).findByText('Нет доступа')).toBeInTheDocument();
  });

  it('истёкшая сессия (401) ведёт на вход', async () => {
    navigationState.pathname = '/requests';
    window.localStorage.setItem('oinau.admin.session', '1');
    net.on('POST', '/api/v1/admin/auth/refresh', errorResponse(401, 'unauthenticated', 'x'));

    renderInPanel(<RequestsList />);

    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith('/login?next=%2Frequests'));
  });
});

// ================================================================== права
describe('права на раздел', () => {
  it('контент-менеджер видит «Нет доступа» и заявки не запрашиваются', async () => {
    signInAs(net, 'CONTENT_MANAGER');

    renderInPanel(<RequestsPage />);

    expect(await screen.findByText('Нет доступа')).toBeInTheDocument();
    expect(net.calls('GET', LIST)).toHaveLength(0);
  });

  it('наблюдатель читает карточку, но не видит действий', async () => {
    await openDetail('VIEWER');

    expect(screen.getByText(/Только просмотр/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Взять в работу' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Новый статус')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Новый комментарий')).not.toBeInTheDocument();
    expect(screen.getByText('Перезвонить после обеда')).toBeInTheDocument();
  });

  it('менеджер может обрабатывать заявку', async () => {
    await openDetail('MANAGER');
    expect(screen.getByRole('button', { name: 'Взять в работу' })).toBeInTheDocument();
    expect(screen.getByLabelText('Новый комментарий')).toBeInTheDocument();
  });
});

// ========================================================== быстрый заказ
describe('быстрый заказ в админке', () => {
  it('запрос КП без позиций подписан источником и в списке, и в фильтре', async () => {
    navigationState.pathname = '/requests';
    net.on(
      'GET',
      LIST,
      page([
        makeRequestListItem({
          id: 3,
          number: 'R-2026-000003',
          kind: 'GENERAL',
          source: 'QUOTE_REQUEST',
          items_count: 0,
          total_estimate: null,
        }),
        makeRequestListItem({
          id: 4,
          number: 'R-2026-000004',
          source: 'SKU_LIST',
          items_count: 3,
        }),
      ]),
    );
    const user = userEvent.setup();

    const table = await openList();
    await within(table).findByRole('link', { name: 'R-2026-000003' });
    const rows = within(table).getAllByRole('row');
    expect(within(rows[1] as HTMLElement).getByText('Запрос КП')).toBeInTheDocument();
    expect(within(rows[2] as HTMLElement).getByText('3 позиции')).toBeInTheDocument();
    expect(within(rows[2] as HTMLElement).getByText('Заказ по артикулам')).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Источник'), 'QUOTE_REQUEST');
    await waitFor(() => expect(lastListParams()?.get('source')).toBe('QUOTE_REQUEST'));
    expect(routerReplace).toHaveBeenLastCalledWith('/requests?source=QUOTE_REQUEST', {
      scroll: false,
    });
  });

  it('источник читается из адреса, неизвестный отбрасывается', () => {
    expect(filtersFromParams(new URLSearchParams('source=ONE_CLICK')).source).toBe('ONE_CLICK');
    expect(filtersFromParams(new URLSearchParams('source=HACK')).source).toBe('');
  });

  it('файл клиента скачивается запросом с токеном', async () => {
    const detail = makeRequestDetail({
      kind: 'GENERAL',
      source: 'QUOTE_REQUEST',
      items: [],
      total_estimate: null,
      bin: '123456789012',
      attachments: [
        {
          id: 91,
          filename: 'Спецификация.pdf',
          content_type: 'application/pdf',
          size_bytes: 245_760,
          created_at: '2026-09-22T05:00:00Z',
        },
      ],
    });
    // jsdom не умеет ни object URL, ни настоящее скачивание.
    vi.stubGlobal(
      'URL',
      Object.assign(URL, { createObjectURL: () => 'blob:x', revokeObjectURL: () => {} }),
    );
    const saved: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      saved.push(this.download);
    });
    net.on('GET', `${DETAIL}/attachments/91`, fileResponse('%PDF-1.7', 'Спецификация.pdf'));
    const user = userEvent.setup();

    await openDetail('MANAGER', detail);

    expect(screen.getByText('Запрос КП · Без позиций')).toBeInTheDocument();
    expect(screen.getByText('123456789012')).toBeInTheDocument();
    expect(screen.getByText('Спецификация.pdf')).toBeInTheDocument();
    expect(screen.getByText(/240 КБ/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Скачать Спецификация.pdf' }));

    await waitFor(() => expect(saved).toEqual(['Спецификация.pdf']));
    const [call] = net.calls('GET', `${DETAIL}/attachments/91`);
    expect(authHeader(call as unknown[])).toMatch(/^Bearer /);
  });
});

// =============================================================== карточка
describe('карточка заявки', () => {
  it('показывает клиента, состав со снапшотами цен, итог, комментарии и историю', async () => {
    await openDetail();

    expect(screen.getByText('Park Group')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '+7 701 555 12 34' })).toHaveAttribute(
      'href',
      'tel:+77015551234',
    );
    expect(screen.getByText('Нужен счёт и сроки поставки')).toBeInTheDocument();
    expect(screen.getByText('Корзина сайта · С позициями')).toBeInTheDocument();

    const items = screen.getByRole('table', { name: 'Позиции заявки' });
    const rows = within(items).getAllByRole('row');
    const rope = within(rows[1] as HTMLElement);
    expect(rope.getByText('KAN-16-PP')).toBeInTheDocument();
    expect(rope.getByText('50 м')).toBeInTheDocument();
    // Цена за единицу и единица измерения — в одной ячейке: «3 050,01 ₸ / м».
    expect(rope.getByText(/^3 050,01 ₸/)).toBeInTheDocument();
    expect(rope.getByText(`152${NBSP}500,50${NBSP}₸`)).toBeInTheDocument();
    // Цвет позиции — снапшот из заявки; у позиции без цвета его нет.
    expect(rope.getByText('Цвет: Красный')).toBeInTheDocument();
    const seat = within(rows[2] as HTMLElement);
    expect(seat.getByText('По запросу')).toBeInTheDocument();
    expect(seat.queryByText(/Цвет:/)).not.toBeInTheDocument();

    expect(screen.getByText('Без учёта позиций с ценой по запросу (1).')).toBeInTheDocument();

    const internal = screen.getByText('Перезвонить после обеда').closest('li') as HTMLElement;
    const visible = screen.getByText('Счёт отправили на почту').closest('li') as HTMLElement;
    expect(within(internal).getByText('Внутренний')).toBeInTheDocument();
    expect(within(visible).getByText('Виден клиенту')).toBeInTheDocument();

    expect(screen.getByText('Заявка создана')).toBeInTheDocument();
  });

  it('несуществующая заявка — понятный экран вместо ошибки', async () => {
    signInAs(net, 'MANAGER');
    net.on('GET', DETAIL, errorResponse(404, 'request_not_found', 'Заявка не найдена'));

    renderInPanel(<RequestDetailScreen id={7} />);

    expect(await screen.findByText('Такой заявки нет')).toBeInTheDocument();
  });

  it('ошибка загрузки карточки с повтором', async () => {
    signInAs(net, 'MANAGER');
    let calls = 0;
    net.on('GET', DETAIL, () => {
      calls += 1;
      return calls === 1
        ? errorResponse(503, 'unavailable', 'Сервис недоступен')
        : jsonResponse(makeRequestDetail());
    });
    const user = userEvent.setup();

    renderInPanel(<RequestDetailScreen id={7} />);
    await user.click(await screen.findByRole('button', { name: 'Повторить' }));

    expect(await screen.findByRole('heading', { name: 'R-2026-000007' })).toBeInTheDocument();
  });
});

// ================================================================ статусы
describe('смена статуса', () => {
  it('предлагает все статусы backend, кроме текущего', async () => {
    await openDetail();
    const options = within(screen.getByLabelText('Новый статус'))
      .getAllByRole('option')
      .map((option) => option.getAttribute('value'))
      .filter(Boolean);
    expect(options).toEqual([
      'IN_PROGRESS',
      'WAITING_CLIENT',
      'QUOTE_SENT',
      'APPROVED',
      'COMPLETED',
      'CANCELLED',
      'SPAM',
    ]);
  });

  it('обычный переход — PATCH с комментарием, обновление карточки и toast', async () => {
    const updated = makeRequestDetail({
      status: 'QUOTE_SENT',
      status_history: [
        ...makeRequestDetail().status_history!,
        {
          id: 32,
          from_status: 'NEW',
          to_status: 'QUOTE_SENT',
          comment: 'КП на почте',
          changed_by: { uuid: '6f1d6a2e-8a3b-4e0e-9f55-1b2c3d4e5f60', full_name: 'Данияр Ахметов' },
          created_at: '2026-09-14T06:00:00Z',
        },
      ],
    });
    net.on('PATCH', `${DETAIL}/status`, updated);
    const user = userEvent.setup();

    await openDetail();
    await user.selectOptions(screen.getByLabelText('Новый статус'), 'QUOTE_SENT');
    await user.type(screen.getByLabelText('Комментарий к переходу'), 'КП на почте');
    await user.click(screen.getByRole('button', { name: 'Сменить статус' }));

    const [call] = net.calls('PATCH', `${DETAIL}/status`);
    expect(JSON.parse(String((call?.[1] as RequestInit).body))).toEqual({
      status: 'QUOTE_SENT',
      comment: 'КП на почте',
    });
    expect(await screen.findByText('Статус изменён')).toBeInTheDocument();
    expect(screen.getByText('КП на почте')).toBeInTheDocument();
    expect(screen.getByLabelText('Новый статус')).toHaveValue('');
    // Подтверждение для рядового перехода не спрашивается.
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('«Взять в работу» переводит новую заявку в IN_PROGRESS', async () => {
    net.on('PATCH', `${DETAIL}/status`, makeRequestDetail({ status: 'IN_PROGRESS' }));
    const user = userEvent.setup();

    await openDetail();
    await user.click(screen.getByRole('button', { name: 'Взять в работу' }));

    const [call] = net.calls('PATCH', `${DETAIL}/status`);
    expect(JSON.parse(String((call?.[1] as RequestInit).body))).toEqual({
      status: 'IN_PROGRESS',
      comment: null,
    });
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Взять в работу' })).not.toBeInTheDocument(),
    );
  });

  it('отмена заявки требует подтверждения; «Отмена» ничего не отправляет', async () => {
    net.on('PATCH', `${DETAIL}/status`, makeRequestDetail({ status: 'CANCELLED' }));
    const user = userEvent.setup();

    await openDetail();
    await user.selectOptions(screen.getByLabelText('Новый статус'), 'CANCELLED');
    await user.click(screen.getByRole('button', { name: 'Сменить статус' }));

    const dialog = await screen.findByRole('dialog', { name: 'Перевести заявку в «Отменена»?' });
    await user.click(within(dialog).getByRole('button', { name: 'Отмена' }));
    expect(net.calls('PATCH', `${DETAIL}/status`)).toHaveLength(0);

    await user.click(screen.getByRole('button', { name: 'Сменить статус' }));
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: 'Сменить статус' }),
    );
    await waitFor(() => expect(net.calls('PATCH', `${DETAIL}/status`)).toHaveLength(1));
  });

  it('403 при смене статуса: сообщение, карточка не меняется', async () => {
    net.on(
      'PATCH',
      `${DETAIL}/status`,
      errorResponse(403, 'permission_denied', 'Недостаточно прав'),
    );
    const user = userEvent.setup();

    await openDetail();
    await user.selectOptions(screen.getByLabelText('Новый статус'), 'QUOTE_SENT');
    await user.click(screen.getByRole('button', { name: 'Сменить статус' }));

    expect(await screen.findByText('Нет права менять статус')).toBeInTheDocument();
    expect(screen.getAllByText('Новая').length).toBeGreaterThan(0);
  });

  it('ошибка валидации backend показывается у поля', async () => {
    net.on(
      'PATCH',
      `${DETAIL}/status`,
      errorResponse(422, 'validation_error', 'Ошибка валидации входных данных', {
        fields: [{ loc: ['body', 'comment'], msg: 'String should have at most 2000 characters' }],
      }),
    );
    const user = userEvent.setup();

    await openDetail();
    await user.selectOptions(screen.getByLabelText('Новый статус'), 'QUOTE_SENT');
    await user.type(screen.getByLabelText('Комментарий к переходу'), 'x');
    await user.click(screen.getByRole('button', { name: 'Сменить статус' }));

    expect(
      await screen.findByText('String should have at most 2000 characters'),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Комментарий к переходу')).toHaveAttribute('aria-invalid', 'true');
  });

  it('заявка удалена, пока была открыта (404) — экран «не найдена»', async () => {
    const user = userEvent.setup();
    await openDetail();
    net.on(
      'PATCH',
      `${DETAIL}/status`,
      errorResponse(404, 'request_not_found', 'Заявка не найдена'),
    );
    net.on('GET', DETAIL, errorResponse(404, 'request_not_found', 'Заявка не найдена'));

    await user.selectOptions(screen.getByLabelText('Новый статус'), 'QUOTE_SENT');
    await user.click(screen.getByRole('button', { name: 'Сменить статус' }));

    expect(await screen.findByText('Такой заявки нет')).toBeInTheDocument();
  });

  it('подтверждение нужно для завершающих статусов и выхода из них', () => {
    expect(needsStatusConfirm('NEW', 'IN_PROGRESS')).toBe(false);
    expect(needsStatusConfirm('NEW', 'SPAM')).toBe(true);
    expect(needsStatusConfirm('COMPLETED', 'IN_PROGRESS')).toBe(true);
    expect(needsStatusConfirm('CANCELLED', 'CANCELLED')).toBe(false);
  });
});

// ============================================================ комментарии
describe('комментарии', () => {
  it('внутренний комментарий по умолчанию — без подтверждения', async () => {
    net.on('POST', `${DETAIL}/comments`, {
      id: 23,
      body: 'Уточнить наличие на складе',
      is_internal: true,
      author: { uuid: '6f1d6a2e-8a3b-4e0e-9f55-1b2c3d4e5f60', full_name: 'Данияр Ахметов' },
      created_at: '2026-09-14T07:00:00Z',
    });
    const user = userEvent.setup();

    await openDetail();
    await user.type(screen.getByLabelText('Новый комментарий'), '  Уточнить наличие на складе ');
    await user.click(screen.getByRole('button', { name: 'Добавить комментарий' }));

    const [call] = net.calls('POST', `${DETAIL}/comments`);
    expect(JSON.parse(String((call?.[1] as RequestInit).body))).toEqual({
      body: 'Уточнить наличие на складе',
      visible_to_customer: false,
    });
    const added = (await screen.findByText('Уточнить наличие на складе')).closest(
      'li',
    ) as HTMLElement;
    expect(within(added).getByText('Внутренний')).toBeInTheDocument();
    expect(screen.getByText('Внутренний комментарий добавлен')).toBeInTheDocument();
    expect(screen.getByLabelText('Новый комментарий')).toHaveValue('');
  });

  it('ответ клиенту — только после подтверждения и с visible_to_customer=true', async () => {
    net.on('POST', `${DETAIL}/comments`, {
      id: 24,
      body: 'Доставка в четверг',
      is_internal: false,
      author: { uuid: '6f1d6a2e-8a3b-4e0e-9f55-1b2c3d4e5f60', full_name: 'Данияр Ахметов' },
      created_at: '2026-09-14T07:00:00Z',
    });
    const user = userEvent.setup();

    await openDetail();
    await user.type(screen.getByLabelText('Новый комментарий'), 'Доставка в четверг');
    await user.click(screen.getByLabelText('Показать клиенту в личном кабинете'));
    await user.click(screen.getByRole('button', { name: 'Отправить клиенту' }));

    const dialog = await screen.findByRole('dialog', { name: 'Отправить ответ клиенту?' });
    expect(net.calls('POST', `${DETAIL}/comments`)).toHaveLength(0);
    await user.click(within(dialog).getByRole('button', { name: 'Отправить клиенту' }));

    await waitFor(() => expect(net.calls('POST', `${DETAIL}/comments`)).toHaveLength(1));
    const [call] = net.calls('POST', `${DETAIL}/comments`);
    expect(JSON.parse(String((call?.[1] as RequestInit).body)).visible_to_customer).toBe(true);
    const added = (await screen.findByText('Доставка в четверг')).closest('li') as HTMLElement;
    expect(within(added).getByText('Виден клиенту')).toBeInTheDocument();
    expect(screen.getByLabelText('Показать клиенту в личном кабинете')).not.toBeChecked();
  });

  it('пустой комментарий не отправляется', async () => {
    await openDetail();
    expect(screen.getByRole('button', { name: 'Добавить комментарий' })).toBeDisabled();
  });

  it('403 при добавлении комментария — сообщение без потери текста', async () => {
    net.on(
      'POST',
      `${DETAIL}/comments`,
      errorResponse(403, 'permission_denied', 'Недостаточно прав'),
    );
    const user = userEvent.setup();

    await openDetail();
    await user.type(screen.getByLabelText('Новый комментарий'), 'Черновик ответа');
    await user.click(screen.getByRole('button', { name: 'Добавить комментарий' }));

    expect(await screen.findByText('Нет права добавлять комментарии')).toBeInTheDocument();
    expect(screen.getByLabelText('Новый комментарий')).toHaveValue('Черновик ответа');
  });
});

// ============================================================ функции
describe('фильтры в адресе', () => {
  it('неизвестные значения отбрасываются', () => {
    const filters = filtersFromParams(
      new URLSearchParams('status=DELETED&sort=price&page=-4&region_id=abc&from=14.09.2026'),
    );
    expect(filters).toMatchObject({
      status: '',
      sort: 'newest',
      page: 1,
      regionId: '',
      dateFrom: '',
    });
  });

  it('границы суток: «по» — начало следующего дня', () => {
    expect(dayStart('2026-12-31')).toBe('2026-12-31T00:00:00+05:00');
    expect(dayEnd('2026-12-31')).toBe('2027-01-01T00:00:00+05:00');
  });
});
