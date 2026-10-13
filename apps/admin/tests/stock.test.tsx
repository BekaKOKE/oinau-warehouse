/**
 * Раздел «Склад»: список остатков (фильтры, сортировка, страницы, мобильные
 * карточки), правка остатков в панели (Decimal строкой, резерв, ошибки),
 * публичное наличие, справочник складов и права.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AppProviders } from '@/components/AppProviders';
import { AuthGate } from '@/components/session/AuthGate';
import { StockScreen } from '@/components/stock/StockScreen';
import type { ProductStockListItem, UserRole } from '@/lib/api/types';
import { resetSessionForTests } from '@/lib/auth/session';

import { createFetchMock, errorResponse, jsonResponse, page, signInAs } from './helpers';
import { makeStock, PRODUCT_URL } from './product-fixtures';
import { navigationState, routerReplace } from './setup';
import {
  emptyStockRow,
  makeStockRow,
  makeWarehouse,
  REGIONS,
  STOCK_LIST,
  WAREHOUSE_LIST,
  WAREHOUSES,
} from './stock-fixtures';

const PRODUCT_STOCK = `${PRODUCT_URL}/stock`;
const AVAILABILITY = `${PRODUCT_URL}/availability`;

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

async function openStock(
  role: UserRole = 'CONTENT_MANAGER',
  rows: ProductStockListItem[] = [makeStockRow(), emptyStockRow()],
  search = '',
) {
  signInAs(net, role);
  navigationState.pathname = '/stock';
  navigationState.search = search;
  net.on('GET', STOCK_LIST, page(rows));
  net.on('GET', WAREHOUSES, page(WAREHOUSE_LIST));
  net.on('GET', PRODUCT_STOCK, makeStock());
  renderInPanel(<StockScreen />);
  return screen.findByRole('table', { name: 'Остатки' });
}

async function openDrawer(role: UserRole = 'CONTENT_MANAGER') {
  const user = userEvent.setup();
  const table = await openStock(role);
  await user.click(
    await within(table).findByRole('button', { name: 'Канат полипропиленовый 16 мм' }),
  );
  const drawer = await screen.findByRole('dialog', { name: 'Канат полипропиленовый 16 мм' });
  await within(drawer).findByText('Фактические остатки');
  await within(drawer).findByRole('listitem', { name: 'Склад «Склад Алматы»' });
  return { user, drawer };
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
describe('список остатков', () => {
  it('строка: товар, SKU, категория, склады, остаток/резерв/свободно, источник, наличие', async () => {
    const table = await openStock();
    await within(table).findByRole('button', { name: 'Канат полипропиленовый 16 мм' });
    const [, ropeRow, seatRow] = within(table).getAllByRole('row');
    const rope = within(ropeRow!);

    expect(rope.getByText('KAN-16-PP')).toBeInTheDocument();
    expect(rope.getByText('1С: 1C-00042')).toBeInTheDocument();
    expect(rope.getByText('Канаты')).toBeInTheDocument();
    // Склады со свободным остатком; отключённый — помечен.
    expect(rope.getByText('Склад Алматы')).toBeInTheDocument();
    expect(rope.getByText('Отключён')).toBeInTheDocument();
    // Итоги — значения backend как есть, без пересчёта.
    const cells = within(ropeRow!).getAllByRole('cell');
    expect(cells[3]).toHaveTextContent('152,5 м');
    expect(cells[4]).toHaveTextContent('2,5 м');
    expect(cells[5]).toHaveTextContent('150 м');
    expect(rope.getByText('Вручную')).toBeInTheDocument();
    expect(rope.getByText('1С')).toBeInTheDocument();
    expect(rope.getByText(/Синхронизация: 13\.09\.2026/)).toBeInTheDocument();
    expect(rope.getByText('В наличии')).toBeInTheDocument();

    const seat = within(seatRow!);
    expect(seat.getByText('Без категории')).toBeInTheDocument();
    expect(seat.getByText('Нет данных')).toBeInTheDocument();
    expect(seat.getByText('Под заказ')).toBeInTheDocument();
    expect(seat.getByTitle(/задан вручную/)).toHaveTextContent('Вручную');
    expect(within(seatRow!).getAllByRole('cell')[5]).toHaveTextContent('0 шт');

    expect(
      screen.getByText(/2 товара\. Остаток, резерв и свободно — итог по активным складам/),
    ).toBeInTheDocument();
    expect(lastParams(STOCK_LIST).get('page_size')).toBe('24');
  });

  it('поиск уходит на backend после паузы и в адрес', async () => {
    const user = userEvent.setup();
    await openStock();
    await user.type(screen.getByLabelText('Поиск'), 'KAN');
    await waitFor(() => expect(lastParams(STOCK_LIST).get('search')).toBe('KAN'));
    expect(routerReplace).toHaveBeenLastCalledWith('/stock?search=KAN', { scroll: false });
  });

  it('склад: запрос warehouse_id, цифры по складу и пояснение', async () => {
    const user = userEvent.setup();
    const table = await openStock();
    await waitFor(() =>
      expect(screen.getByLabelText('Склад')).toContainHTML('Склад Астана (отключён)'),
    );
    await user.selectOptions(screen.getByLabelText('Склад'), '2');

    await waitFor(() => expect(lastParams(STOCK_LIST).get('warehouse_id')).toBe('2'));
    expect(routerReplace).toHaveBeenLastCalledWith('/stock?warehouse=2', { scroll: false });
    expect(
      screen.getByText(/по складу «Склад Астана» \(склад отключён и не входит в наличие\)/),
    ).toBeInTheDocument();
    const ropeRow = within(table).getAllByRole('row')[1]!;
    expect(within(ropeRow).getAllByRole('cell')[3]).toHaveTextContent('40 м');
    // У второго товара строки на этом складе нет.
    expect(within(within(table).getAllByRole('row')[2]!).getAllByRole('cell')[3]).toHaveTextContent(
      '—',
    );
  });

  it('источник, наличие на сайте и сортировка — в запрос; «Сбросить фильтры»', async () => {
    const user = userEvent.setup();
    await openStock();
    await user.selectOptions(screen.getByLabelText('Источник'), '1c');
    await waitFor(() => expect(lastParams(STOCK_LIST).get('sync_source')).toBe('1c'));
    await user.selectOptions(screen.getByLabelText('Наличие на сайте'), 'OUT_OF_STOCK');
    await waitFor(() => expect(lastParams(STOCK_LIST).get('availability')).toBe('OUT_OF_STOCK'));
    await user.selectOptions(screen.getByLabelText('Сортировка'), 'available_asc');
    await waitFor(() => expect(lastParams(STOCK_LIST).get('sort')).toBe('available_asc'));
    expect(lastParams(STOCK_LIST).get('sync_source')).toBe('1c');

    await user.click(screen.getByRole('button', { name: 'Сбросить фильтры' }));
    await waitFor(() => expect(lastParams(STOCK_LIST).get('sync_source')).toBeNull());
    expect(lastParams(STOCK_LIST).get('availability')).toBeNull();
    expect(lastParams(STOCK_LIST).get('sort')).toBe('available_asc');
  });

  it('фильтры из адреса применяются сразу', async () => {
    await openStock(
      'CONTENT_MANAGER',
      [makeStockRow()],
      'warehouse=1&source=manual&availability=IN_STOCK&sort=updated&page=2&search=кан',
    );
    const params = lastParams(STOCK_LIST);
    expect(params.get('warehouse_id')).toBe('1');
    expect(params.get('sync_source')).toBe('manual');
    expect(params.get('availability')).toBe('IN_STOCK');
    expect(params.get('sort')).toBe('updated');
    expect(params.get('page')).toBe('2');
    expect(params.get('search')).toBe('кан');
    expect(screen.getByLabelText('Поиск')).toHaveValue('кан');
  });

  it('страницы', async () => {
    const user = userEvent.setup();
    net.on('GET', STOCK_LIST, page([makeStockRow()], 30));
    signInAs(net, 'CONTENT_MANAGER');
    net.on('GET', WAREHOUSES, page(WAREHOUSE_LIST));
    renderInPanel(<StockScreen />);
    await user.click(await screen.findByRole('button', { name: 'Следующая страница' }));
    await waitFor(() => expect(lastParams(STOCK_LIST).get('page')).toBe('2'));
  });

  it('загрузка, ошибка с повтором, пустой список и пустой результат фильтра', async () => {
    let release: (value: Response) => void = () => undefined;
    signInAs(net, 'CONTENT_MANAGER');
    net.on('GET', WAREHOUSES, page(WAREHOUSE_LIST));
    net.on('GET', STOCK_LIST, () => new Promise<Response>((resolve) => (release = resolve)));
    renderInPanel(<StockScreen />);
    const table = await screen.findByRole('table', { name: 'Остатки' });
    expect(table).toHaveAttribute('aria-busy', 'true');

    release(errorResponse(500, 'internal_error', 'Сбой'));
    const user = userEvent.setup();
    await user.click(await within(table).findByRole('button', { name: 'Повторить' }));
    release(jsonResponse(page([])));
    expect(await within(table).findByText('Товаров пока нет')).toBeInTheDocument();
  });

  it('пусто при фильтре — «Ничего не найдено»', async () => {
    const table = await openStock('CONTENT_MANAGER', [], 'availability=OUT_OF_STOCK');
    expect(await within(table).findByText('Ничего не найдено')).toBeInTheDocument();
  });

  it('403 — «Нет доступа»; 401 — переход на вход', async () => {
    signInAs(net, 'CONTENT_MANAGER');
    net.on('GET', WAREHOUSES, page(WAREHOUSE_LIST));
    net.on('GET', STOCK_LIST, errorResponse(403, 'permission_denied', 'Недостаточно прав'));
    const first = renderInPanel(<StockScreen />);
    const table = await screen.findByRole('table', { name: 'Остатки' });
    expect(await within(table).findByText('Нет доступа')).toBeInTheDocument();
    first.unmount();

    resetSessionForTests();
    navigationState.pathname = '/stock';
    net.on('POST', '/api/v1/admin/auth/refresh', errorResponse(401, 'unauthenticated', 'x'));
    renderInPanel(<StockScreen />);
    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith('/login?next=%2Fstock'));
  });

  it('мобильные карточки: три показателя и наличие; касание открывает панель', async () => {
    const user = userEvent.setup();
    await openStock();
    const mobile = screen.getByTestId('mobile-list');
    const card = within(
      await within(mobile)
        .findByText('Канат полипропиленовый 16 мм')
        .then((node) => node.closest('li') as HTMLElement),
    );
    expect(card.getByText('KAN-16-PP · Канаты')).toBeInTheDocument();
    expect(card.getByText('Остаток').nextSibling).toHaveTextContent('152,5');
    expect(card.getByText('Резерв').nextSibling).toHaveTextContent('2,5');
    expect(card.getByText('Свободно').nextSibling).toHaveTextContent('150 м');
    expect(card.getByText('В наличии')).toBeInTheDocument();

    await user.click(card.getByText('Остаток'));
    expect(
      await screen.findByRole('dialog', { name: 'Канат полипропиленовый 16 мм' }),
    ).toBeInTheDocument();
  });

  it('вкладка «Склады» — в адрес', async () => {
    const user = userEvent.setup();
    await openStock();
    await user.click(screen.getByRole('tab', { name: 'Склады' }));
    expect(routerReplace).toHaveBeenCalledWith('/stock?tab=warehouses', { scroll: false });
  });
});

// ================================================================ правка
describe('правка остатков в панели', () => {
  it('показатели по складам, данные синхронизации, предупреждение о 1С', async () => {
    const { drawer } = await openDrawer();
    expect(
      within(drawer).getByText('Ручное изменение используется до подключения 1C.'),
    ).toBeInTheDocument();

    const almaty = within(within(drawer).getByRole('listitem', { name: 'Склад «Склад Алматы»' }));
    expect(almaty.getByLabelText('Остаток, м')).toHaveValue('152.5');
    expect(almaty.getByLabelText('Резерв, м')).toHaveValue('2.5');
    expect(almaty.getByTestId('available-1')).toHaveTextContent('150 м');
    expect(almaty.getByText('Вручную')).toBeInTheDocument();

    const astana = within(within(drawer).getByRole('listitem', { name: 'Склад «Склад Астана»' }));
    expect(astana.getByText('Склад отключён — не входит в наличие')).toBeInTheDocument();
    expect(astana.queryByRole('textbox')).not.toBeInTheDocument();
    expect(astana.getByText('1C-WH-2')).toBeInTheDocument();
    expect(astana.getByText('1С')).toBeInTheDocument();
    expect(astana.getAllByText(/13\.09\.2026/, { selector: 'dd' })).toHaveLength(2);
    expect(within(drawer).getByTestId('total-available')).toHaveTextContent('150 м');
  });

  it('сохраняет только изменённый склад строками; показывает свободный остаток из ответа', async () => {
    const saved = makeStock({
      entries: [
        {
          ...makeStock().entries![0]!,
          quantity: '160.250',
          reserved: '10.000',
          available: '150.250',
        },
        makeStock().entries![1]!,
      ],
      total_quantity: '160.250',
      total_reserved: '10.000',
      total_available: '150.250',
    });
    net.on('PUT', PRODUCT_STOCK, saved);
    const { user, drawer } = await openDrawer();
    const almaty = within(within(drawer).getByRole('listitem', { name: 'Склад «Склад Алматы»' }));

    await user.clear(almaty.getByLabelText('Остаток, м'));
    await user.type(almaty.getByLabelText('Остаток, м'), '160,25');
    await user.clear(almaty.getByLabelText('Резерв, м'));
    await user.type(almaty.getByLabelText('Резерв, м'), '10');
    // Свободный остаток не пересчитывается на экране — только после ответа.
    expect(almaty.getByTestId('available-1')).toHaveTextContent('150 м');
    expect(almaty.getByText('Пересчитается после сохранения')).toBeInTheDocument();

    await user.click(within(drawer).getByRole('button', { name: 'Сохранить остатки' }));
    await waitFor(() => expect(net.calls('PUT', PRODUCT_STOCK)).toHaveLength(1));
    expect(bodyOf('PUT', PRODUCT_STOCK)).toEqual({
      items: [{ warehouse_id: 1, quantity: '160.25', reserved: '10' }],
    });
    expect(await screen.findByText('Остатки сохранены')).toBeInTheDocument();
    expect(await within(drawer).findByTestId('available-1')).toHaveTextContent('150,25 м');
    expect(within(drawer).getByTestId('total-available')).toHaveTextContent('150,25 м');
    await waitFor(() => expect(net.calls('GET', STOCK_LIST)).toHaveLength(2));
  });

  it('Decimal: большие значения без округления, лишние знаки не отправляются', async () => {
    net.on('PUT', PRODUCT_STOCK, makeStock());
    const { user, drawer } = await openDrawer();
    const almaty = within(within(drawer).getByRole('listitem', { name: 'Склад «Склад Алматы»' }));
    const quantity = almaty.getByLabelText('Остаток, м');

    await user.clear(quantity);
    await user.type(quantity, '1,2345');
    await user.click(within(drawer).getByRole('button', { name: 'Сохранить остатки' }));
    expect(quantity).toHaveAccessibleDescription('Не больше 3 знаков после запятой');
    expect(net.calls('PUT', PRODUCT_STOCK)).toHaveLength(0);

    await user.clear(quantity);
    await user.type(quantity, '99999999999.999');
    await user.click(within(drawer).getByRole('button', { name: 'Сохранить остатки' }));
    await waitFor(() => expect(net.calls('PUT', PRODUCT_STOCK)).toHaveLength(1));
    expect(bodyOf('PUT', PRODUCT_STOCK)).toEqual({
      items: [{ warehouse_id: 1, quantity: '99999999999.999', reserved: '2.5' }],
    });
  });

  it('резерв больше остатка — ошибка у резерва, запрос не уходит', async () => {
    const { user, drawer } = await openDrawer();
    const almaty = within(within(drawer).getByRole('listitem', { name: 'Склад «Склад Алматы»' }));
    await user.clear(almaty.getByLabelText('Резерв, м'));
    await user.type(almaty.getByLabelText('Резерв, м'), '152.501');
    await user.click(within(drawer).getByRole('button', { name: 'Сохранить остатки' }));
    expect(almaty.getByLabelText('Резерв, м')).toHaveAccessibleDescription('Резерв больше остатка');
    expect(net.calls('PUT', PRODUCT_STOCK)).toHaveLength(0);

    await user.click(within(drawer).getByRole('button', { name: 'Отменить' }));
    expect(almaty.getByLabelText('Резерв, м')).toHaveValue('2.5');
  });

  it('422 backend — у поля склада', async () => {
    net.on(
      'PUT',
      PRODUCT_STOCK,
      errorResponse(422, 'validation_error', 'Ошибка', {
        fields: [{ loc: ['body', 'items', 0], msg: 'Value error, Резерв 3 больше остатка 2' }],
      }),
    );
    const { user, drawer } = await openDrawer();
    const almaty = within(within(drawer).getByRole('listitem', { name: 'Склад «Склад Алматы»' }));
    await user.clear(almaty.getByLabelText('Остаток, м'));
    await user.type(almaty.getByLabelText('Остаток, м'), '200');
    await user.click(within(drawer).getByRole('button', { name: 'Сохранить остатки' }));
    await waitFor(() =>
      expect(almaty.getByLabelText('Резерв, м')).toHaveAccessibleDescription(
        /Резерв 3 больше остатка 2/,
      ),
    );
  });

  it('409 «склад отключён» и 404 — объяснение и перечитывание данных', async () => {
    net.on(
      'PUT',
      PRODUCT_STOCK,
      errorResponse(409, 'warehouse_inactive', 'Нельзя задать остаток на отключённом складе'),
    );
    const { user, drawer } = await openDrawer();
    const almaty = within(within(drawer).getByRole('listitem', { name: 'Склад «Склад Алматы»' }));
    await user.clear(almaty.getByLabelText('Остаток, м'));
    await user.type(almaty.getByLabelText('Остаток, м'), '10');
    await user.click(within(drawer).getByRole('button', { name: 'Сохранить остатки' }));
    expect(await screen.findByText('Склад отключён')).toBeInTheDocument();
    await waitFor(() => expect(net.calls('GET', PRODUCT_STOCK)).toHaveLength(2));

    net.on('PUT', PRODUCT_STOCK, errorResponse(404, 'not_found', 'Склад 1 не найден'));
    const field = await within(
      within(drawer).getByRole('listitem', { name: 'Склад «Склад Алматы»' }),
    ).findByLabelText('Остаток, м');
    await user.clear(field);
    await user.type(field, '20');
    await user.click(within(drawer).getByRole('button', { name: 'Сохранить остатки' }));
    expect(await screen.findByText('Товар или склад не найден')).toBeInTheDocument();
  });

  it('403 при сохранении не маскируется', async () => {
    net.on('PUT', PRODUCT_STOCK, errorResponse(403, 'permission_denied', 'Недостаточно прав'));
    const { user, drawer } = await openDrawer();
    const almaty = within(within(drawer).getByRole('listitem', { name: 'Склад «Склад Алматы»' }));
    await user.type(almaty.getByLabelText('Остаток, м'), '1');
    await user.click(within(drawer).getByRole('button', { name: 'Сохранить остатки' }));
    expect(await screen.findByText('Нет права изменять остатки')).toBeInTheDocument();
  });

  it('товар не найден при открытии панели', async () => {
    const user = userEvent.setup();
    const table = await openStock();
    net.on('GET', PRODUCT_STOCK, errorResponse(404, 'not_found', 'Товар не найден'));
    await user.click(
      await within(table).findByRole('button', { name: 'Канат полипропиленовый 16 мм' }),
    );
    expect(await screen.findByText(/Товар не найден — возможно, он удалён/)).toBeInTheDocument();
  });
});

// ======================================================= публичное наличие
describe('публичное наличие', () => {
  it('переопределение — отдельный PATCH, остатки не трогаются; статус из ответа сервера', async () => {
    net.on('PATCH', AVAILABILITY, {
      product_id: 5,
      sku: 'KAN-16-PP',
      stock_display_override: 'OUT_OF_STOCK',
      public_availability: 'OUT_OF_STOCK',
      total_available: '150.000',
    });
    const { user, drawer } = await openDrawer();
    const section = within(
      within(drawer).getByText('Публичное наличие').closest('section') as HTMLElement,
    );
    expect(
      section.getByText(/Фактический остаток и публичное наличие — разные вещи/),
    ).toBeInTheDocument();
    expect(section.getByText('Переопределение не меняет остаток и резерв.')).toBeInTheDocument();
    expect(section.getByText('По остаткам')).toBeInTheDocument();
    expect(section.getByRole('button', { name: 'Применить' })).toBeDisabled();

    net.on(
      'GET',
      PRODUCT_STOCK,
      makeStock({ stock_display_override: 'OUT_OF_STOCK', public_availability: 'OUT_OF_STOCK' }),
    );
    await user.selectOptions(section.getByLabelText('Показ наличия'), 'OUT_OF_STOCK');
    await user.click(section.getByRole('button', { name: 'Применить' }));

    await waitFor(() => expect(net.calls('PATCH', AVAILABILITY)).toHaveLength(1));
    expect(bodyOf('PATCH', AVAILABILITY)).toEqual({ stock_display_override: 'OUT_OF_STOCK' });
    expect(net.calls('PUT', PRODUCT_STOCK)).toHaveLength(0);
    expect(await screen.findByText('Показ наличия задан вручную')).toBeInTheDocument();
    expect(await section.findByText('Задано вручную')).toBeInTheDocument();
    expect(section.getByText('Нет в наличии')).toBeInTheDocument();
    await waitFor(() => expect(net.calls('GET', STOCK_LIST)).toHaveLength(2));
  });

  it('снятие переопределения — null; 403 и удалённый товар объясняются', async () => {
    net.on(
      'GET',
      PRODUCT_STOCK,
      makeStock({ stock_display_override: 'ON_REQUEST', public_availability: 'ON_REQUEST' }),
    );
    net.on('PATCH', AVAILABILITY, errorResponse(409, 'product_deleted', 'Товар удалён'));
    const user = userEvent.setup();
    const table = await openStock();
    net.on(
      'GET',
      PRODUCT_STOCK,
      makeStock({ stock_display_override: 'ON_REQUEST', public_availability: 'ON_REQUEST' }),
    );
    await user.click(
      await within(table).findByRole('button', { name: 'Канат полипропиленовый 16 мм' }),
    );
    const drawer = await screen.findByRole('dialog');
    const select = await within(drawer).findByLabelText('Показ наличия');
    expect(select).toHaveValue('ON_REQUEST');

    await user.selectOptions(select, '');
    await user.click(within(drawer).getByRole('button', { name: 'Применить' }));
    await waitFor(() =>
      expect(bodyOf('PATCH', AVAILABILITY)).toEqual({ stock_display_override: null }),
    );
    expect(await screen.findByText('Товар удалён — наличие не меняется')).toBeInTheDocument();

    net.on('PATCH', AVAILABILITY, errorResponse(403, 'permission_denied', 'Недостаточно прав'));
    await user.click(within(drawer).getByRole('button', { name: 'Применить' }));
    expect(await screen.findByText('Нет права изменять наличие')).toBeInTheDocument();
  });
});

// ================================================================ права
describe('права на склад', () => {
  it('менеджер видит остатки и наличие только для чтения', async () => {
    const { drawer } = await openDrawer('MANAGER');
    expect(within(drawer).queryByRole('textbox')).not.toBeInTheDocument();
    expect(
      within(drawer).queryByText('Ручное изменение используется до подключения 1C.'),
    ).not.toBeInTheDocument();
    expect(
      within(drawer).queryByRole('button', { name: 'Сохранить остатки' }),
    ).not.toBeInTheDocument();
    expect(within(drawer).getByText(/Только просмотр/)).toBeInTheDocument();
    expect(within(drawer).getByLabelText('Показ наличия')).toBeDisabled();
    expect(within(drawer).queryByRole('button', { name: 'Применить' })).not.toBeInTheDocument();
    const almaty = within(within(drawer).getByRole('listitem', { name: 'Склад «Склад Алматы»' }));
    expect(almaty.getByText('Остаток').nextSibling).toHaveTextContent('152,5 м');
  });

  it('менеджер: склады без создания и правки', async () => {
    signInAs(net, 'MANAGER');
    navigationState.search = 'tab=warehouses';
    net.on('GET', WAREHOUSES, page(WAREHOUSE_LIST));
    renderInPanel(<StockScreen />);
    const table = await screen.findByRole('table', { name: 'Склады' });
    await within(table).findByText('Склад Алматы');
    expect(screen.queryByRole('button', { name: 'Новый склад' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Изменить склад/ })).not.toBeInTheDocument();
  });
});

// ================================================================ склады
async function openWarehouses(items = WAREHOUSE_LIST) {
  signInAs(net, 'CONTENT_MANAGER');
  navigationState.pathname = '/stock';
  navigationState.search = 'tab=warehouses';
  net.on('GET', WAREHOUSES, page(items));
  net.on('GET', REGIONS, [
    { id: 1, code: 'almaty', name: 'Алматы' },
    { id: 3, code: 'astana', name: 'Астана' },
  ]);
  renderInPanel(<StockScreen />);
  const table = await screen.findByRole('table', { name: 'Склады' });
  return table;
}

describe('склады', () => {
  it('список: название, код, регион, внешний код, источник, статус', async () => {
    const table = await openWarehouses();
    await within(table).findByText('Склад Алматы');
    const [, almatyRow, astanaRow] = within(table).getAllByRole('row');
    const almaty = within(almatyRow!);
    expect(almaty.getByText('main')).toBeInTheDocument();
    expect(almaty.getByText('Алматы')).toBeInTheDocument();
    expect(almaty.getByText('Вручную')).toBeInTheDocument();
    expect(almaty.getByText('Активен')).toBeInTheDocument();
    const astana = within(astanaRow!);
    expect(astana.getByText('1C-WH-2')).toBeInTheDocument();
    expect(astana.getByText('1С')).toBeInTheDocument();
    expect(astana.getByText('Отключён')).toBeInTheDocument();
    expect(screen.getByText(/2 склада/)).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Склады' })).toHaveAttribute('aria-selected', 'true');
  });

  it('фильтр статуса — в запрос; пустой справочник', async () => {
    const user = userEvent.setup();
    await openWarehouses();
    net.on('GET', WAREHOUSES, page([]));
    await user.selectOptions(screen.getByLabelText('Статус склада'), 'false');
    await waitFor(() => expect(lastParams(WAREHOUSES).get('is_active')).toBe('false'));
    expect(await screen.findAllByText('Таких складов нет')).not.toHaveLength(0);
  });

  it('ошибка загрузки складов с повтором', async () => {
    signInAs(net, 'CONTENT_MANAGER');
    navigationState.search = 'tab=warehouses';
    net.on('GET', WAREHOUSES, errorResponse(500, 'internal_error', 'Сбой'));
    renderInPanel(<StockScreen />);
    const table = await screen.findByRole('table', { name: 'Склады' });
    net.on('GET', WAREHOUSES, page([]));
    await userEvent.setup().click(await within(table).findByRole('button', { name: 'Повторить' }));
    expect(await within(table).findByText('Складов пока нет')).toBeInTheDocument();
  });

  it('создание: проверка полей, POST и обновление списка', async () => {
    net.on('POST', WAREHOUSES, makeWarehouse({ id: 3, code: 'astana-2', name: 'Склад Астана 2' }));
    const user = userEvent.setup();
    await openWarehouses();
    await user.click(screen.getByRole('button', { name: 'Новый склад' }));
    const dialog = await screen.findByRole('dialog', { name: 'Новый склад' });

    await user.type(within(dialog).getByRole('textbox', { name: 'Код' }), 'Astana 2');
    await user.click(within(dialog).getByRole('button', { name: 'Создать' }));
    expect(within(dialog).getByLabelText(/Название/)).toHaveAttribute('aria-invalid', 'true');
    expect(within(dialog).getByRole('textbox', { name: 'Код' })).toHaveAccessibleDescription(
      'Только строчная латиница, цифры, «-» и «_»',
    );
    expect(net.calls('POST', WAREHOUSES)).toHaveLength(0);

    await user.type(within(dialog).getByLabelText(/Название/), 'Склад Астана 2');
    await user.clear(within(dialog).getByRole('textbox', { name: 'Код' }));
    await user.type(within(dialog).getByRole('textbox', { name: 'Код' }), 'astana-2');
    await waitFor(() => expect(within(dialog).getByLabelText('Регион')).toContainHTML('Астана'));
    await user.selectOptions(within(dialog).getByLabelText('Регион'), '3');
    await user.type(within(dialog).getByLabelText('Код во внешней системе'), '1C-WH-3');
    await user.click(within(dialog).getByRole('button', { name: 'Создать' }));

    await waitFor(() => expect(net.calls('POST', WAREHOUSES)).toHaveLength(1));
    expect(bodyOf('POST', WAREHOUSES)).toEqual({
      code: 'astana-2',
      name: 'Склад Астана 2',
      region_id: 3,
      external_id: '1C-WH-3',
      is_active: true,
    });
    expect(await screen.findByText('Склад создан')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(net.calls('GET', WAREHOUSES)).toHaveLength(2);
  });

  it('409 «код занят» и 422 — у полей', async () => {
    net.on(
      'POST',
      WAREHOUSES,
      errorResponse(409, 'warehouse_code_exists', 'Склад с таким кодом уже существует'),
    );
    const user = userEvent.setup();
    await openWarehouses();
    await user.click(screen.getByRole('button', { name: 'Новый склад' }));
    const dialog = await screen.findByRole('dialog', { name: 'Новый склад' });
    await user.type(within(dialog).getByLabelText(/Название/), 'Дубль');
    await user.type(within(dialog).getByRole('textbox', { name: 'Код' }), 'main');
    await user.click(within(dialog).getByRole('button', { name: 'Создать' }));
    expect(await within(dialog).findByRole('textbox', { name: 'Код' })).toHaveAccessibleDescription(
      'Склад с таким кодом уже существует',
    );

    net.on(
      'POST',
      WAREHOUSES,
      errorResponse(422, 'validation_error', 'x', {
        fields: [{ loc: ['body', 'name'], msg: 'Слишком длинно' }],
      }),
    );
    await user.clear(within(dialog).getByRole('textbox', { name: 'Код' }));
    await user.type(within(dialog).getByRole('textbox', { name: 'Код' }), 'new');
    await user.click(within(dialog).getByRole('button', { name: 'Создать' }));
    expect(await within(dialog).findByLabelText(/Название/)).toHaveAccessibleDescription(
      'Слишком длинно',
    );
  });

  it('правка: код не меняется, PATCH только изменений', async () => {
    net.on('PATCH', `${WAREHOUSES}/1`, makeWarehouse({ name: 'Склад Алматы — центр' }));
    const user = userEvent.setup();
    await openWarehouses();
    await user.click(await screen.findByRole('button', { name: 'Изменить склад «Склад Алматы»' }));
    const dialog = await screen.findByRole('dialog', { name: 'Склад «Склад Алматы»' });
    expect(within(dialog).getByTestId('warehouse-code')).toHaveTextContent('main');
    expect(within(dialog).getByTestId('warehouse-code')).toHaveTextContent('Не меняется');
    expect(within(dialog).queryByRole('textbox', { name: 'Код' })).not.toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Сохранить' })).toBeDisabled();

    await user.type(within(dialog).getByLabelText(/Название/), ' — центр');
    await user.click(within(dialog).getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(net.calls('PATCH', `${WAREHOUSES}/1`)).toHaveLength(1));
    expect(bodyOf('PATCH', `${WAREHOUSES}/1`)).toEqual({ name: 'Склад Алматы — центр' });
    expect(await screen.findByText('Склад сохранён')).toBeInTheDocument();
  });

  it('отключение — с подтверждением; отказ ничего не отправляет', async () => {
    net.on('PATCH', `${WAREHOUSES}/1`, makeWarehouse({ is_active: false }));
    const user = userEvent.setup();
    await openWarehouses();
    await user.click(await screen.findByRole('button', { name: 'Изменить склад «Склад Алматы»' }));
    const dialog = await screen.findByRole('dialog', { name: 'Склад «Склад Алматы»' });
    await user.click(within(dialog).getByRole('switch', { name: /Активен/ }));
    await user.click(within(dialog).getByRole('button', { name: 'Сохранить' }));

    const confirm = await screen.findByRole('dialog', { name: 'Отключить склад «Склад Алматы»?' });
    expect(confirm).toHaveTextContent('перестанут учитываться в наличии');
    await user.click(within(confirm).getByRole('button', { name: 'Отмена' }));
    expect(net.calls('PATCH', `${WAREHOUSES}/1`)).toHaveLength(0);

    await user.click(within(dialog).getByRole('button', { name: 'Сохранить' }));
    await user.click(
      within(await screen.findByRole('dialog', { name: /Отключить склад/ })).getByRole('button', {
        name: 'Отключить',
      }),
    );
    await waitFor(() => expect(bodyOf('PATCH', `${WAREHOUSES}/1`)).toEqual({ is_active: false }));
  });

  it('409 внешнего кода, 404 и 403 при правке', async () => {
    net.on(
      'PATCH',
      `${WAREHOUSES}/2`,
      errorResponse(409, 'external_id_exists', 'Внешний код занят'),
    );
    const user = userEvent.setup();
    await openWarehouses();
    await user.click(await screen.findByRole('button', { name: 'Изменить склад «Склад Астана»' }));
    const dialog = await screen.findByRole('dialog', { name: 'Склад «Склад Астана»' });
    const external = within(dialog).getByLabelText('Код во внешней системе');
    await user.clear(external);
    await user.type(external, '1C-WH-1');
    await user.click(within(dialog).getByRole('button', { name: 'Сохранить' }));
    expect(
      await within(dialog).findByLabelText('Код во внешней системе'),
    ).toHaveAccessibleDescription('Внешний код занят');

    net.on('PATCH', `${WAREHOUSES}/2`, errorResponse(404, 'not_found', 'Склад не найден'));
    await user.click(within(dialog).getByRole('button', { name: 'Сохранить' }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Склад не найден');
    await waitFor(() => expect(net.calls('GET', WAREHOUSES).length).toBeGreaterThan(1));

    net.on(
      'PATCH',
      `${WAREHOUSES}/2`,
      errorResponse(403, 'permission_denied', 'Недостаточно прав'),
    );
    await user.click(within(dialog).getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findByText('Нет права изменять склады')).toBeInTheDocument();
  });
});
