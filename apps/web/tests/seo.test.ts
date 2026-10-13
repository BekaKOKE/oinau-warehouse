/**
 * Метаданные страниц: бренд в заголовке, canonical, OpenGraph и noindex.
 */

import { describe, expect, it } from 'vitest';

import { buildMetadata, metadataFromSeo, titleWithBrand } from '@/lib/seo';

describe('titleWithBrand', () => {
  it('добавляет название компании к заголовку страницы', () => {
    expect(titleWithBrand('Каталог комплектующих')).toBe('Каталог комплектующих — OINAU PRO');
  });

  it('не приписывает бренд второй раз', () => {
    // Заголовок из CMS часто уже содержит название компании.
    expect(titleWithBrand('OINAU PRO — комплектующие для площадок')).toBe(
      'OINAU PRO — комплектующие для площадок',
    );
    expect(titleWithBrand('Канат Ø16 мм — OINAU PRO')).toBe('Канат Ø16 мм — OINAU PRO');
  });
});

describe('buildMetadata', () => {
  it('заголовок абсолютный — шаблон макета его не дополняет', () => {
    const meta = buildMetadata({ title: 'Канат Ø16 мм', path: '/product/kanat' });
    expect(meta.title).toEqual({ absolute: 'Канат Ø16 мм — OINAU PRO' });
  });

  it('canonical и OpenGraph строятся от адреса сайта', () => {
    const meta = buildMetadata({
      title: 'Каталог',
      description: 'Комплектующие',
      path: '/catalog',
    });
    expect(meta.alternates?.canonical).toBe('http://localhost:3000/catalog');
    expect(meta.openGraph?.url).toBe('http://localhost:3000/catalog');
    expect(meta.openGraph?.title).toBe('Каталог — OINAU PRO');
    expect(meta.description).toBe('Комплектующие');
  });

  it('страницы поиска и постраничная выдача закрыты от индексации', () => {
    expect(buildMetadata({ title: 'Поиск', path: '/catalog', noindex: true }).robots).toEqual({
      index: false,
      follow: true,
    });
    expect(buildMetadata({ title: 'Каталог', path: '/catalog' }).robots).toEqual({
      index: true,
      follow: true,
    });
  });
});

describe('metadataFromSeo', () => {
  it('значения CMS имеют приоритет над запасными', () => {
    const meta = metadataFromSeo(
      {
        title: 'Доставка по Казахстану',
        description: 'Условия доставки',
        og_title: null,
        og_description: null,
        og_image: null,
      },
      { title: 'Доставка', description: 'Запасное описание', path: '/delivery' },
    );
    expect(meta.title).toEqual({ absolute: 'Доставка по Казахстану — OINAU PRO' });
    expect(meta.description).toBe('Условия доставки');
  });

  it('без данных CMS берутся запасные значения страницы', () => {
    const meta = metadataFromSeo(null, {
      title: 'Доставка',
      description: 'Запасное описание',
      path: '/delivery',
    });
    expect(meta.title).toEqual({ absolute: 'Доставка — OINAU PRO' });
    expect(meta.description).toBe('Запасное описание');
  });
});
