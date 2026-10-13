/**
 * Таблица товаров раздела: цены по количеству, наличие, характеристики,
 * заказ из строки и адаптивный список карточек.
 */

import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { PriceInfo, ProductListItem } from '@oinau/api-types';

import { ProductTable, productFeatures } from '@/components/catalog/ProductTable';
import { ProductTableLoader } from '@/components/catalog/ProductTableLoader';
import { Providers } from '@/components/layout/Providers';
import { priceAt, tierColumns } from '@/lib/price-table';
import { fixedPrice, makeProduct, makeProductPage, onRequestPrice, tieredPrice } from './factories';

const seatPrice: PriceInfo = {
  type: 'TIERED',
  currency: 'KZT',
  price: null,
  from_price: '3250.00',
  to_price: '3900.00',
  tiers: [
    { min_quantity: '1.000', max_quantity: '99.999', price: '3900.00' },
    { min_quantity: '100.000', max_quantity: '999.999', price: '3650.00' },
    { min_quantity: '1000.000', max_quantity: null, price: '3250.00' },
  ],
};

function seat(overrides: Partial<ProductListItem> = {}): ProductListItem {
  return makeProduct({
    sku: '504-176',
    slug: 'krugloe-sidene-504-176',
    name: 'Круглое сиденье без подвесов',
    unit: 'pcs',
    price: seatPrice,
    characteristics: [{ code: 'color', name: 'Цвет', value: 'чёрный' }],
    specs: { Материал: 'резина', Цвет: 'чёрный' },
    ...overrides,
  });
}

function renderTable(products: ProductListItem[]) {
  return render(
    <Providers>
      <ProductTable products={products} />
    </Providers>,
  );
}

describe('priceAt и tierColumns', () => {
  it('цена колонки — ступень, в которую попадает количество', () => {
    expect(priceAt(seatPrice, 1)).toBe('3900.00');
    expect(priceAt(seatPrice, 100)).toBe('3650.00');
    expect(priceAt(seatPrice, 5000)).toBe('3250.00');
    expect(priceAt(fixedPrice, 1000)).toBe('15900.00');
    expect(priceAt(onRequestPrice, 1)).toBeNull();
  });

  it('общие колонки — только когда ступени совпадают по смыслу', () => {
    expect(tierColumns([seat(), seat({ sku: 'X' })])).toEqual([1, 100, 1000]);
    // Одна цена у всех — отдельных колонок не нужно
    expect(tierColumns([makeProduct({ price: fixedPrice })])).toBeNull();
  });
});

describe('ProductTable', () => {
  it('строка: артикул, название, характеристики, цены по количеству, наличие', () => {
    renderTable([seat()]);
    const table = screen.getByRole('table');
    const headers = within(table)
      .getAllByRole('columnheader')
      .map((cell) => cell.textContent?.replace(/\s+/g, ' '));
    expect(headers).toEqual([
      'Фото',
      'Артикул',
      'Наименование',
      'от 1',
      'от 100',
      'от 1 000',
      'Наличие',
      'Заказ',
    ]);

    const [row] = within(table).getAllByRole('row').slice(1);
    expect(row).toBeDefined();
    const cells = within(row!).getAllByRole('cell');
    expect(cells[1]).toHaveTextContent('504-176');
    expect(
      within(cells[2]!).getByRole('link', { name: 'Круглое сиденье без подвесов' }),
    ).toHaveAttribute('href', '/product/krugloe-sidene-504-176');
    expect(cells[2]).toHaveTextContent('Цветчёрный');
    expect(cells[2]).toHaveTextContent('Материалрезина');
    // Знак валюты — у самих цен, а не в заголовке колонки.
    expect(cells[3]).toHaveTextContent('3 900 ₸');
    expect(cells[4]).toHaveTextContent('3 650');
    expect(cells[5]).toHaveTextContent('3 250');
    expect(cells[6]).toHaveTextContent('В наличии');
  });

  it('цена по запросу занимает все колонки цен', () => {
    renderTable([seat(), seat({ sku: 'REQ-1', slug: 'req', price: onRequestPrice })]);
    const table = screen.getByRole('table');
    expect(within(table).getByText('Цена по запросу').closest('td')).toHaveAttribute(
      'colspan',
      '3',
    );
  });

  it('разные ступени — список цен в одной колонке', () => {
    const many: PriceInfo = {
      ...tieredPrice,
      tiers: [10, 20, 30, 40, 60].map((quantity) => ({
        min_quantity: `${quantity}.000`,
        max_quantity: null,
        price: '100.00',
      })),
    };
    renderTable([makeProduct({ price: tieredPrice }), makeProduct({ sku: 'M-2', price: many })]);
    const table = screen.getByRole('table');
    expect(within(table).getByRole('columnheader', { name: 'Цена' })).toBeInTheDocument();
    expect(within(table).getByText('1–49')).toBeInTheDocument();
    expect(within(table).getByText('от 50')).toBeInTheDocument();
  });

  it('точный остаток не показывается — только статус', () => {
    renderTable([seat({ availability: 'OUT_OF_STOCK' })]);
    expect(within(screen.getByRole('table')).getByText('Нет в наличии')).toBeInTheDocument();
  });

  it('«В корзину» добавляет позицию с выбранным количеством', async () => {
    const user = userEvent.setup();
    renderTable([seat({ min_order_qty: '10.000' })]);
    const table = screen.getByRole('table');
    const qty = within(table).getByRole('spinbutton', { name: 'Количество, шт: 504-176' });
    expect(qty).toHaveValue(10);
    await user.clear(qty);
    await user.type(qty, '250');
    await user.click(within(table).getByRole('button', { name: 'Добавить в корзину' }));
    expect(within(table).getByRole('button', { name: 'Добавлено в корзину' })).toBeInTheDocument();
  });

  it('на телефоне та же выдача — списком карточек', () => {
    renderTable([seat()]);
    const list = screen.getByRole('list', { name: 'Товары раздела' });
    expect(within(list).getByText('арт. 504-176')).toBeInTheDocument();
    expect(within(list).getByRole('button', { name: /1 клик/ })).toBeInTheDocument();
  });

  it('характеристики без повторов и не больше четырёх', () => {
    const features = productFeatures(
      seat({
        specs: { Цвет: 'чёрный', A: '1', B: '2', C: '3', D: '4' },
      }),
    );
    expect(features.map((item) => item.name)).toEqual(['Цвет', 'A', 'B', 'C']);
  });
});

describe('ProductTableLoader', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('«Показать ещё» дописывает следующую страницу', async () => {
    const user = userEvent.setup();
    const next = makeProductPage([seat({ sku: 'NEXT-1', slug: 'next-1' })], {
      page: 2,
      pages: 2,
      total: 2,
    });
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(JSON.stringify(next), { status: 200 }));

    render(
      <Providers>
        <ProductTableLoader
          initialItems={[seat()]}
          query={{ category: 'kachelі', attrs: ['color:black'], pageSize: 1 }}
          page={1}
          pages={2}
          total={2}
        />
      </Providers>,
    );
    await user.click(screen.getByRole('button', { name: 'Показать ещё (осталось 1)' }));

    const table = await screen.findByRole('table');
    expect((await within(table).findAllByText('NEXT-1')).length).toBeGreaterThan(0);
    expect(within(table).getAllByText('504-176').length).toBeGreaterThan(0);
    const url = String(fetchMock.mock.calls[0]?.[0]);
    expect(url).toContain('page=2');
    expect(url).toContain('attr=color%3Ablack');
    expect(screen.queryByRole('button', { name: /Показать ещё/ })).not.toBeInTheDocument();
  });
});
