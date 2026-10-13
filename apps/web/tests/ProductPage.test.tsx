/**
 * Страница товара в стиле B2B-каталога: цены по количеству таблицей,
 * цвет, характеристики, упаковка и отдельный блок схемы.
 */

import { render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ProductDetail } from '@oinau/api-types';

import { Providers } from '@/components/layout/Providers';
import { SchemeBlock, canOpen } from '@/components/product/SchemeBlock';
import { ServiceList } from '@/components/services/ServiceList';
import { productSections } from '@/lib/product-sections';
import { makeProductDetail } from './factories';

const pdf = {
  url: 'https://cdn.oinau-pro.kz/products/u1/variants/file.pdf',
  kind: 'SCHEME',
  filename: '504-176.pdf',
  content_type: 'application/pdf',
  size_bytes: 245760,
  preview_url: null,
};
const dwg = {
  url: 'https://cdn.oinau-pro.kz/products/u2/variants/file.dwg',
  kind: 'DRAWING',
  filename: 'plan.dwg',
  content_type: 'image/vnd.dwg',
  size_bytes: 2 * 1024 * 1024,
  preview_url: null,
};
const image = {
  url: 'https://cdn.oinau-pro.kz/products/u3/variants/large.webp',
  kind: 'SCHEME',
  filename: 'scheme.jpg',
  content_type: 'image/webp',
  size_bytes: null,
  preview_url: 'https://cdn.oinau-pro.kz/products/u3/variants/medium.webp',
};

describe('SchemeBlock', () => {
  it('PDF можно открыть и скачать', () => {
    render(<SchemeBlock documents={[pdf]} productName="Сиденье" />);
    const block = screen.getByRole('region', { name: 'Схема изделия' });
    expect(within(block).getByText('504-176.pdf')).toBeInTheDocument();
    expect(within(block).getByText('Схема · PDF · 240 КБ')).toBeInTheDocument();
    const open = within(block).getByRole('link', { name: 'Открыть схему' });
    expect(open).toHaveAttribute('href', pdf.url);
    expect(open).toHaveAttribute('target', '_blank');
    expect(within(block).getByRole('link', { name: 'Скачать' })).toHaveAttribute(
      'download',
      '504-176.pdf',
    );
  });

  it('DWG только скачивается, изображение показывает превью', () => {
    render(<SchemeBlock documents={[dwg, image]} productName="Сиденье" />);
    expect(screen.getAllByRole('link', { name: 'Открыть схему' })).toHaveLength(1);
    expect(screen.getAllByRole('link', { name: 'Скачать' })).toHaveLength(2);
    expect(screen.getByRole('img', { name: 'Схема: Сиденье' })).toHaveAttribute(
      'src',
      image.preview_url,
    );
    expect(canOpen(dwg)).toBe(false);
    expect(canOpen(pdf)).toBe(true);
  });

  it('без схем блок не выводится', () => {
    const { container } = render(<SchemeBlock documents={[]} productName="X" />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe('productSections', () => {
  it('раскладывает цвет, характеристики и упаковку', () => {
    const product: ProductDetail = makeProductDetail({
      characteristics: [
        { code: 'color', name: 'Цвет', value: 'чёрный' },
        { code: 'diameter', name: 'Диаметр', value: '16 мм' },
      ],
      specs: { Цвет: 'чёрный', 'В упаковке': '50 шт', Материал: 'резина' },
    });
    const sections = productSections(product);
    expect(sections.color).toBe('чёрный');
    expect(sections.characteristics.map((row) => row.name)).toEqual([
      'Цвет',
      'Диаметр',
      'Материал',
    ]);
    expect(sections.packaging.map((row) => [row.name, row.value])).toEqual([
      ['В упаковке', '50 шт'],
    ]);
  });

  it('без цвета — null', () => {
    expect(productSections(makeProductDetail()).color).toBeNull();
  });
});

describe('ServiceList', () => {
  afterEach(() => vi.restoreAllMocks());

  it('услуга: название, что делаем, условия и две кнопки', () => {
    render(
      <Providers>
        <ServiceList
          whatsappUrl="https://wa.me/77010000000"
          items={[
            {
              slug: 'obzhimka-kanatov',
              title: 'Обжимка канатов',
              summary: 'Опрессовка втулками.',
              details: ['Алюминиевые втулки', 'Канат 16 мм'],
              price_note: 'По объёму партии',
              image: null,
              cta_label: null,
            },
          ]}
        />
      </Providers>,
    );
    const item = screen.getByRole('heading', { name: 'Обжимка канатов' }).closest('li');
    expect(item).toHaveAttribute('id', 'obzhimka-kanatov');
    expect(within(item!).getByText('Что делаем')).toBeInTheDocument();
    expect(within(item!).getByText('Канат 16 мм')).toBeInTheDocument();
    expect(within(item!).getByText('По объёму партии')).toBeInTheDocument();
    expect(within(item!).getByRole('button', { name: 'Оставить заявку' })).toBeInTheDocument();
    expect(within(item!).getByRole('link', { name: 'Получить консультацию' })).toHaveAttribute(
      'href',
      'https://wa.me/77010000000',
    );
  });
});
