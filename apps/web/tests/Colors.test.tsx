/**
 * Цвета товара на витрине: выбор цвета на странице товара (цена с
 * надбавкой, наличие цвета), позиции корзины по цвету, отправка цвета
 * в заявке и подсказка в каталоге.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { PriceInfo, ProductColorDetail } from '@oinau/api-types';

import { ProductCard } from '@/components/catalog/ProductCard';
import { ProductTable } from '@/components/catalog/ProductTable';
import { Providers } from '@/components/layout/Providers';
import { SiteHeader } from '@/components/layout/SiteHeader';
import { BuyBox } from '@/components/product/BuyBox';
import { lineKey } from '@/lib/request-line';
import { makeCategories, makeProduct, makeProductDetail, tieredPrice } from './factories';

const fetchRegions = vi.fn();
const submitRequest = vi.fn();

vi.mock('@/lib/api/requests', () => ({
  fetchRegions: () => fetchRegions(),
  submitRequest: (...args: unknown[]) => submitRequest(...args),
  newIdempotencyKey: () => 'test-idempotency-key',
}));

function shifted(delta: number): PriceInfo {
  return {
    ...tieredPrice,
    from_price: String(2600 + delta),
    to_price: String(3500 + delta),
    tiers: (tieredPrice.tiers ?? []).map((tier) => ({
      ...tier,
      price: (Number(tier.price) + delta).toFixed(2),
    })),
  };
}

const COLORS: ProductColorDetail[] = [
  { code: 'black', name: 'Чёрный', hex: '#1f1f1f', availability: 'IN_STOCK', price: tieredPrice },
  { code: 'red', name: 'Красный', hex: '#d32f2f', availability: 'IN_STOCK', price: shifted(200) },
  { code: 'blue', name: 'Синий', hex: '#1976d2', availability: 'OUT_OF_STOCK', price: tieredPrice },
];

function renderBuyBox(colors = COLORS) {
  return render(
    <Providers>
      <SiteHeader categories={makeCategories()} />
      <BuyBox product={makeProductDetail({ colors })} />
    </Providers>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  fetchRegions.mockResolvedValue([]);
  submitRequest.mockReset();
});

describe('выбор цвета на странице товара', () => {
  it('по умолчанию — первый цвет в наличии; у цвета своё наличие', () => {
    renderBuyBox();
    const group = screen.getByRole('group', { name: /Цвет:/ });
    expect(within(group).getByRole('radio', { name: 'Чёрный, в наличии' })).toBeChecked();
    expect(within(group).getByRole('radio', { name: 'Синий, нет в наличии' })).not.toBeChecked();
    expect(group).toHaveTextContent('Цвет: Чёрный · В наличии');
  });

  it('цвет с надбавкой меняет цены по количеству', async () => {
    const user = userEvent.setup();
    renderBuyBox();
    const table = screen.getByRole('table', { name: 'Цены по количеству' });
    expect(within(table).getByText('3 500 ₸')).toBeInTheDocument();

    await user.click(screen.getByRole('radio', { name: 'Красный, в наличии' }));
    expect(within(table).getByText('3 700 ₸')).toBeInTheDocument();
    expect(within(table).getByText('2 800 ₸')).toBeInTheDocument();
  });

  it('один товар в двух цветах — две позиции корзины, цвет уходит в заявку', async () => {
    const user = userEvent.setup();
    submitRequest.mockResolvedValue({
      number: 'R-2026-000150',
      created_at: '2026-10-05T10:00:00Z',
      currency: 'KZT',
      total_estimate: null,
      items: [],
    });
    renderBuyBox();

    await user.click(screen.getByRole('button', { name: 'Добавить в корзину' }));
    // Корзина открывается после добавления — закрываем и выбираем другой цвет.
    await screen.findByRole('dialog', { name: 'Корзина' });
    await user.keyboard('{Escape}');
    await user.click(screen.getByRole('radio', { name: 'Красный, в наличии' }));
    await user.click(screen.getByRole('button', { name: 'Добавить в корзину' }));

    const dialog = await screen.findByRole('dialog', { name: 'Корзина' });
    expect(within(dialog).getByText('Цвет: Чёрный')).toBeInTheDocument();
    expect(within(dialog).getByText('Цвет: Красный')).toBeInTheDocument();
    expect(
      within(dialog).getByRole('button', {
        name: 'Убрать из корзины: Канат армированный Ø16 мм, Красный',
      }),
    ).toBeInTheDocument();

    await user.type(within(dialog).getByLabelText(/Имя/), 'Иван');
    await user.type(within(dialog).getByLabelText(/Телефон/), '+7 701 123 45 67');
    await user.click(within(dialog).getByRole('button', { name: 'Отправить заявку' }));

    await waitFor(() => expect(submitRequest).toHaveBeenCalledTimes(1));
    const [payload] = submitRequest.mock.calls[0] as [{ items: unknown[] }];
    expect(payload.items).toEqual([
      { sku: 'RP-016', quantity: '5', color: 'black' },
      { sku: 'RP-016', quantity: '5', color: 'red' },
    ]);
  });

  it('товар без цветов — без выбора цвета и без цвета в заявке', () => {
    renderBuyBox([]);
    expect(screen.queryByRole('group', { name: /Цвет:/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Добавить в корзину' })).toBeInTheDocument();
  });
});

describe('цвета в каталоге', () => {
  const colored = makeProduct({
    colors: COLORS.map(({ price: _price, ...color }) => color),
  });

  it('карточка: образцы цветов и переход к выбору цвета вместо «В корзину»', () => {
    render(
      <Providers>
        <ProductCard product={colored} />
      </Providers>,
    );
    expect(screen.getByLabelText('Цвета: Чёрный, Красный, Синий')).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Выбрать цвет: Канат армированный Ø16 мм' }),
    ).toHaveAttribute('href', '/product/kanat-armirovannyj-16-mm');
    expect(screen.queryByRole('button', { name: /В корзину/ })).not.toBeInTheDocument();
  });

  it('таблица: в строке товара с цветами — ссылка на выбор цвета', () => {
    render(
      <Providers>
        <ProductTable products={[colored, makeProduct({ sku: 'X-1', slug: 'x-1' })]} />
      </Providers>,
    );
    const table = screen.getByRole('table');
    expect(within(table).getByRole('link', { name: 'Выбрать цвет: RP-016' })).toBeInTheDocument();
    // Товар без цветов заказывается прямо из строки
    expect(
      within(table).getByRole('spinbutton', { name: 'Количество, м: X-1' }),
    ).toBeInTheDocument();
  });
});

describe('ключ позиции', () => {
  it('артикул и цвет', () => {
    expect(lineKey({ sku: 'RP-016' })).toBe('RP-016');
    expect(lineKey({ sku: 'RP-016', color: 'red' })).toBe('RP-016:red');
  });

  it('старая корзина без цвета читается', async () => {
    window.localStorage.setItem(
      'oinau.request.v1',
      JSON.stringify([
        {
          sku: 'RP-016',
          slug: 'kanat',
          name: 'Канат',
          unit: 'm',
          quantity: 3,
          minOrderQty: 1,
          priceLabel: '—',
        },
      ]),
    );
    render(
      <Providers>
        <SiteHeader categories={makeCategories()} />
      </Providers>,
    );
    expect(await screen.findByRole('button', { name: 'Корзина: 1' })).toBeInTheDocument();
  });
});
