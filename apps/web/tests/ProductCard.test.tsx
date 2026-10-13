/**
 * Карточка товара: артикул, наличие, цена по типу и заглушка вместо
 * отсутствующего изображения.
 */

import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { ProductCard } from '@/components/catalog/ProductCard';
import { ProductGrid } from '@/components/catalog/ProductGrid';
import { Providers } from '@/components/layout/Providers';
import { fixedPrice, fromPrice, makeProduct, onRequestPrice } from './factories';

function renderCard(product = makeProduct()) {
  return render(
    <Providers>
      <ProductCard product={product} />
    </Providers>,
  );
}

describe('ProductCard', () => {
  it('показывает название, артикул и наличие', () => {
    renderCard();
    expect(screen.getByText('Канат армированный Ø16 мм')).toBeInTheDocument();
    // Артикул есть и в заглушке изображения, и в строке под названием.
    expect(screen.getAllByText('RP-016').length).toBeGreaterThan(0);
    expect(screen.getByText('В наличии')).toBeInTheDocument();
  });

  it('ведёт на страницу товара', () => {
    renderCard();
    const link = screen.getByRole('link', { name: 'Канат армированный Ø16 мм' });
    expect(link).toHaveAttribute('href', '/product/kanat-armirovannyj-16-mm');
  });

  it('для ступенчатой цены показывает «от»', () => {
    renderCard();
    expect(screen.getByText('от')).toBeInTheDocument();
    expect(screen.getByText('2 600')).toBeInTheDocument();
    expect(screen.getByText('₸ / м')).toBeInTheDocument();
  });

  it('для фиксированной цены показывает сумму без приставки', () => {
    renderCard(makeProduct({ price: fixedPrice, unit: 'pcs' }));
    expect(screen.getByText('15 900')).toBeInTheDocument();
    expect(screen.queryByText('от')).not.toBeInTheDocument();
  });

  it('для цены по запросу предлагает запросить стоимость', () => {
    renderCard(makeProduct({ price: onRequestPrice, availability: 'ON_REQUEST', sku: 'SL-250' }));
    expect(screen.getByText('Цена по запросу')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Запросить стоимость' })).toBeInTheDocument();
    expect(screen.getByText('Под заказ')).toBeInTheDocument();
  });

  it('вместо отсутствующего изображения показывает брендированную заглушку', () => {
    const { container } = renderCard();
    expect(screen.getByText('OINAU PRO')).toBeInTheDocument();
    // Артикул виден дважды: в заглушке и в строке под названием.
    expect(screen.getAllByText('RP-016')).toHaveLength(2);
    expect(container.querySelector('img')).toBeNull();
  });

  it('изображение из медиатеки берётся по готовой ссылке варианта', () => {
    renderCard(
      makeProduct({
        image: {
          url: 'http://localhost:9000/oinau-media/products/1/variants/large.webp',
          kind: 'PHOTO',
          alt: 'Канат',
          is_main: true,
          width: 1600,
          height: 1200,
          variants: {
            large: 'http://localhost:9000/oinau-media/products/1/variants/large.webp',
            thumb: 'http://localhost:9000/oinau-media/products/1/variants/thumb.webp',
          },
        },
      }),
    );
    // Ссылка-картинка скрыта от средств чтения с экрана: она дублирует
    // ссылку с названием, поэтому ищем изображение вместе со скрытыми.
    const image = screen.getByRole('img', { name: 'Канат', hidden: true });
    expect(image).toHaveAttribute('src', expect.stringContaining('variants/large.webp'));
  });

  it('порядок карточки как в макете: наличие, артикул, название, цена, кнопки', () => {
    const { container } = renderCard();
    // Суммы форматируются с неразрывным пробелом — сравниваем по обычному.
    const text = (container.querySelector('article')?.textContent ?? '').replace(/\u00a0/g, ' ');
    const order = [
      'В наличии',
      'арт. RP-016',
      'Канат армированный Ø16 мм',
      '2 600',
      'В корзину',
      '1 клик',
    ].map((part) => text.lastIndexOf(part));
    expect(order.every((position) => position >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
  });

  it('короткая подпись кнопки не теряет полное доступное имя', () => {
    renderCard();
    const button = screen.getByRole('button', { name: 'Добавить в корзину' });
    expect(button).toHaveTextContent('В корзину');
  });

  it('показывает оптовую ступень из прайса, а не выдуманную скидку', () => {
    renderCard();
    expect(screen.getByText(/^от 50 м — 2\s600 ₸$/)).toBeInTheDocument();
  });

  it('у фиксированной цены оптовой строки нет', () => {
    renderCard(makeProduct({ price: fixedPrice, unit: 'pcs' }));
    expect(screen.queryByText(/^от .+ —/)).not.toBeInTheDocument();
  });

  it('«1 клик» открывает быстрый заказ с этим товаром', async () => {
    const user = userEvent.setup();
    renderCard();

    await user.click(screen.getByRole('button', { name: '1 клик: Канат армированный Ø16 мм' }));

    const dialog = screen.getByRole('dialog', { name: 'Быстрый заказ' });
    expect(within(dialog).getByRole('tab', { name: 'По телефону' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(within(dialog).getByText('Канат армированный Ø16 мм')).toBeInTheDocument();
  });

  it('для цены «от» показывает приставку и сумму без выдумывания', () => {
    renderCard(makeProduct({ price: fromPrice, unit: 'pcs' }));
    expect(screen.getByText('от')).toBeInTheDocument();
    expect(screen.getByText('2 800')).toBeInTheDocument();
    expect(screen.getByText('₸ / шт')).toBeInTheDocument();
  });

  it('отмечает хит продаж', () => {
    renderCard(makeProduct({ is_featured: true }));
    expect(screen.getByText('Хит')).toBeInTheDocument();
  });
});

describe('ProductGrid', () => {
  it('выводит все переданные позиции', () => {
    render(
      <Providers>
        <ProductGrid
          products={[
            makeProduct(),
            makeProduct({ sku: 'HN-301', slug: 'podves', name: 'Подвес качели' }),
          ]}
        />
      </Providers>,
    );
    expect(screen.getByText('Канат армированный Ø16 мм')).toBeInTheDocument();
    expect(screen.getByText('Подвес качели')).toBeInTheDocument();
  });
});
