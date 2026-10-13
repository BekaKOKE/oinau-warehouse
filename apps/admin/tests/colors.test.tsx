/**
 * Цвета: вкладка «Цвета» в карточке товара (остаток и надбавка по цвету,
 * сверка с общим остатком, права) и справочник цветов.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AppProviders } from '@/components/AppProviders';
import { ColorsScreen } from '@/components/colors/ColorsScreen';
import { ProductEditorScreen } from '@/components/products/ProductEditorScreen';
import { AuthGate } from '@/components/session/AuthGate';
import type { Color, ProductColors, UserRole } from '@/lib/api/types';
import { resetSessionForTests } from '@/lib/auth/session';
import { buildColorItems, totalsMismatch } from '@/lib/colors';

import { createFetchMock, errorResponse, signInAs } from './helpers';
import {
  CATEGORY_ATTRIBUTES,
  CATEGORY_TREE,
  MATERIAL_ATTRIBUTE,
  makeProduct,
  PRODUCT_ID,
  PRODUCT_URL,
} from './product-fixtures';
import { navigationState } from './setup';

const COLORS = '/api/v1/admin/colors';
const PRODUCT_COLORS = `${PRODUCT_URL}/colors`;

let net: ReturnType<typeof createFetchMock>;

function makeColor(overrides: Partial<Color> = {}): Color {
  return {
    id: 1,
    code: 'black',
    name: 'Чёрный',
    hex: '#1f1f1f',
    sort_order: 0,
    is_active: true,
    products_count: 1,
    ...overrides,
  };
}

const PALETTE: Color[] = [
  makeColor(),
  makeColor({ id: 2, code: 'red', name: 'Красный', hex: '#d32f2f', products_count: 0 }),
  makeColor({ id: 3, code: 'blue', name: 'Синий', hex: '#1976d2', products_count: 0 }),
  makeColor({ id: 4, code: 'pink', name: 'Розовый', hex: '#ff80ab', is_active: false }),
];

function makeProductColors(overrides: Partial<ProductColors> = {}): ProductColors {
  return {
    product_id: PRODUCT_ID,
    sku: 'KAN-16-PP',
    unit: 'm',
    items: [
      {
        color_id: 1,
        code: 'black',
        name: 'Чёрный',
        hex: '#1f1f1f',
        color_is_active: true,
        quantity: '100.000',
        price_delta: '0.00',
        public_availability: 'IN_STOCK',
      },
    ],
    colors_total: '100.000',
    stock_total: '150.000',
    ...overrides,
  };
}

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

async function openColorsTab(role: UserRole = 'CONTENT_MANAGER', colors = makeProductColors()) {
  signInAs(net, role);
  const product = makeProduct();
  net.on('GET', PRODUCT_URL, product);
  net.on('GET', '/api/v1/admin/categories/tree', CATEGORY_TREE);
  net.on('GET', '/api/v1/admin/categories/2/attributes', CATEGORY_ATTRIBUTES);
  net.on('GET', '/api/v1/admin/categories/3/attributes', []);
  net.on('GET', '/api/v1/admin/attributes/11', MATERIAL_ATTRIBUTE);
  net.on('GET', PRODUCT_COLORS, colors);
  net.on('GET', COLORS, PALETTE);
  navigationState.search = 'tab=colors';
  renderInPanel(<ProductEditorScreen id={PRODUCT_ID} />);
  await screen.findByRole('heading', { name: product.name });
  return screen.findByRole('list', { name: 'Цвета товара' });
}

beforeEach(() => {
  resetSessionForTests();
  net = createFetchMock();
  vi.stubGlobal('fetch', net.mock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ============================================================== вкладка
describe('цвета товара', () => {
  it('показывает цвета, статус на сайте и расхождение с остатком на складах', async () => {
    const list = await openColorsTab();
    expect(within(list).getByText('Чёрный')).toBeInTheDocument();
    expect(within(list).getByLabelText('Остаток: Чёрный')).toHaveValue('100');
    expect(within(list).getByText('В наличии')).toBeInTheDocument();
    expect(screen.getByText(/на складах свободно 150 м/)).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(
      'Сумма по цветам не совпадает с остатком на складах',
    );
  });

  it('добавление цвета и сохранение — полный набор в PUT', async () => {
    const user = userEvent.setup();
    await openColorsTab();
    net.on('PUT', PRODUCT_COLORS, makeProductColors({ colors_total: '150.000' }));

    // Отключённого цвета нет среди доступных
    const add = screen.getByLabelText('Добавить цвет');
    expect(within(add).queryByRole('option', { name: 'Розовый' })).not.toBeInTheDocument();
    await user.selectOptions(add, '2');
    await user.click(screen.getByRole('button', { name: 'Добавить' }));

    const quantity = screen.getByLabelText('Остаток: Красный');
    await user.clear(quantity);
    await user.type(quantity, '50');
    const delta = screen.getByLabelText('Надбавка: Красный');
    await user.clear(delta);
    await user.type(delta, '200');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(net.calls('PUT', PRODUCT_COLORS)).toHaveLength(1));
    expect(bodyOf('PUT', PRODUCT_COLORS)).toEqual({
      items: [
        { color_id: 1, quantity: '100', price_delta: '0' },
        { color_id: 2, quantity: '50', price_delta: '200' },
      ],
    });
    expect(await screen.findByText('Цвета сохранены')).toBeInTheDocument();
  });

  it('удаление цвета и проверка числа до отправки', async () => {
    const user = userEvent.setup();
    await openColorsTab();
    const quantity = screen.getByLabelText('Остаток: Чёрный');
    await user.clear(quantity);
    await user.type(quantity, '1,2345');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findByText('Не больше 3 знаков после запятой')).toBeInTheDocument();
    expect(net.calls('PUT', PRODUCT_COLORS)).toHaveLength(0);

    net.on('PUT', PRODUCT_COLORS, makeProductColors({ items: [], colors_total: '0' }));
    await user.click(screen.getByRole('button', { name: 'Убрать цвет Чёрный' }));
    expect(screen.getByText('Цвета не заданы')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(bodyOf('PUT', PRODUCT_COLORS)).toEqual({ items: [] }));
  });

  it('ошибка сохранения показывается сообщением', async () => {
    const user = userEvent.setup();
    await openColorsTab();
    net.on(
      'PUT',
      PRODUCT_COLORS,
      errorResponse(409, 'color_inactive', 'Цвет отключён в справочнике'),
    );
    const quantity = screen.getByLabelText('Остаток: Чёрный');
    await user.clear(quantity);
    await user.type(quantity, '90');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findByText('Цвета не сохранены')).toBeInTheDocument();
  });

  it('без прав на остатки и цены — только просмотр', async () => {
    const list = await openColorsTab('MANAGER');
    expect(within(list).getByLabelText('Остаток: Чёрный')).toBeDisabled();
    expect(screen.queryByLabelText('Добавить цвет')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Сохранить' })).not.toBeInTheDocument();
  });
});

describe('помощники цветов', () => {
  it('тело запроса: запятая в числе, пустое поле — ноль', () => {
    expect(buildColorItems([{ colorId: 2, quantity: '12,5', priceDelta: '' }]).body.items).toEqual([
      { color_id: 2, quantity: '12.5', price_delta: '0' },
    ]);
    expect(buildColorItems([{ colorId: 2, quantity: '-1', priceDelta: '0' }]).errors).toEqual({
      '2.quantity': 'Введите неотрицательное число',
    });
  });

  it('расхождение сумм: строки сравниваются как числа', () => {
    expect(totalsMismatch(makeProductColors({ colors_total: '150', stock_total: '150.000' }))).toBe(
      false,
    );
    expect(totalsMismatch(makeProductColors())).toBe(true);
    // Без цветов сравнивать нечего
    expect(totalsMismatch(makeProductColors({ items: [], colors_total: '0' }))).toBe(false);
  });
});

// ============================================================ справочник
describe('справочник цветов', () => {
  async function openDictionary(role: UserRole = 'CONTENT_MANAGER') {
    signInAs(net, role);
    navigationState.pathname = '/colors';
    net.on('GET', COLORS, PALETTE);
    renderInPanel(<ColorsScreen />);
    const table = await screen.findByRole('table', { name: 'Справочник цветов' });
    await within(table).findByText('black');
    return table;
  }

  it('список: образец, код, использование и статус', async () => {
    const table = await openDictionary();
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(4);
    expect(within(rows[0]!).getByText('black')).toBeInTheDocument();
    expect(within(rows[3]!).getByText('Отключён')).toBeInTheDocument();
    // Используемый цвет удалить нельзя — кнопки нет
    expect(within(rows[0]!).queryByRole('button', { name: /Удалить/ })).not.toBeInTheDocument();
    expect(within(rows[1]!).getByRole('button', { name: 'Удалить цвет Красный' })).toBeEnabled();
  });

  it('создание: код идёт за названием, образец строкой', async () => {
    const user = userEvent.setup();
    await openDictionary();
    net.on('POST', COLORS, makeColor({ id: 9, code: 'oranzhevyy', name: 'Оранжевый' }));
    await user.click(screen.getByRole('button', { name: 'Новый цвет' }));
    const dialog = await screen.findByRole('dialog', { name: 'Новый цвет' });
    await user.type(within(dialog).getByLabelText(/Название/), 'Оранжевый');
    expect(within(dialog).getByLabelText(/^Код/)).toHaveValue('oranzhevyy');
    const hex = within(dialog).getByLabelText('Образец, #RRGGBB');
    await user.clear(hex);
    await user.type(hex, '#F57C00');
    await user.click(within(dialog).getByRole('button', { name: 'Создать' }));

    await waitFor(() => expect(net.calls('POST', COLORS)).toHaveLength(1));
    expect(bodyOf('POST', COLORS)).toEqual({
      code: 'oranzhevyy',
      name: 'Оранжевый',
      hex: '#F57C00',
      sort_order: 0,
      is_active: true,
    });
    expect(await screen.findByText('Цвет создан')).toBeInTheDocument();
  });

  it('правка: код не меняется, неверный образец не отправляется', async () => {
    const user = userEvent.setup();
    const table = await openDictionary();
    net.on('PATCH', `${COLORS}/2`, makeColor({ id: 2, name: 'Алый' }));
    await user.click(within(table).getByRole('button', { name: 'Красный' }));
    const dialog = await screen.findByRole('dialog', { name: 'Цвет «Красный»' });
    expect(within(dialog).getByLabelText(/^Код/)).toBeDisabled();

    const hex = within(dialog).getByLabelText('Образец, #RRGGBB');
    await user.clear(hex);
    await user.type(hex, 'red');
    await user.click(within(dialog).getByRole('button', { name: 'Сохранить' }));
    expect(await within(dialog).findByText('Формат #RRGGBB')).toBeInTheDocument();
    expect(net.calls('PATCH', `${COLORS}/2`)).toHaveLength(0);

    await user.clear(hex);
    await user.type(hex, '#c62828');
    const name = within(dialog).getByLabelText(/Название/);
    await user.clear(name);
    await user.type(name, 'Алый');
    await user.click(within(dialog).getByRole('button', { name: 'Сохранить' }));
    await waitFor(() =>
      expect(bodyOf('PATCH', `${COLORS}/2`)).toEqual({
        name: 'Алый',
        hex: '#c62828',
        sort_order: 0,
        is_active: true,
      }),
    );
  });

  it('удаление неиспользуемого цвета после подтверждения', async () => {
    const user = userEvent.setup();
    const table = await openDictionary();
    net.on('DELETE', `${COLORS}/2`, {
      ok: true,
      status: 204,
      json: async () => null,
    } as unknown as Response);
    await user.click(within(table).getByRole('button', { name: 'Удалить цвет Красный' }));
    const confirm = await screen.findByRole('dialog', { name: 'Удалить цвет «Красный»?' });
    await user.click(within(confirm).getByRole('button', { name: 'Удалить' }));
    await waitFor(() => expect(net.calls('DELETE', `${COLORS}/2`)).toHaveLength(1));
    expect(await screen.findByText('Цвет удалён')).toBeInTheDocument();
  });

  it('просмотр без права изменения: нет кнопок', async () => {
    const table = await openDictionary('VIEWER');
    expect(screen.queryByRole('button', { name: 'Новый цвет' })).not.toBeInTheDocument();
    expect(within(table).queryByRole('button', { name: /Удалить/ })).not.toBeInTheDocument();
  });
});
