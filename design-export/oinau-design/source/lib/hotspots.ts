/**
 * Точки на фотографии площадки в hero.
 *
 * Backend не хранит «узлы площадки» как сущность: у него есть каталог.
 * Поэтому координаты и привязка к разделу живут здесь, а название,
 * количество позиций и ссылка берутся из реального дерева категорий.
 * Когда такая сущность появится в API, поменяется только эта функция —
 * компонент `PlaygroundHotspots` данных не придумывает.
 *
 * `x`/`y` — проценты от размеров изображения. Значения промерены по
 * самому снимку: точка стоит на своём узле площадки, а плашка
 * раскрывается в свободную сторону, чтобы не залезать на соседнюю
 * и не уходить за край кадра (закреплено тестами в States.test.tsx).
 */

import type { CategoryNode } from '@oinau/api-types';

import { catalogHref } from '@/lib/catalog-params';
import { findCategory } from '@/lib/api/catalog';

export type HotspotConfig = {
  id: string;
  /** Подпись, если категория с таким slug ещё не заведена. */
  title: string;
  /** Slug категории каталога. */
  category: string;
  x: number;
  y: number;
  /** Плашка разворачивается вправо от точки, иначе — влево. */
  alignRight?: boolean;
  hue: string;
};

export const HOTSPOTS: readonly HotspotConfig[] = [
  {
    id: 'roof',
    title: 'Крыша',
    category: 'plastikovye-detali',
    x: 58,
    y: 8,
    alignRight: true,
    hue: '#a06bff',
  },
  {
    id: 'fasteners',
    title: 'Крепёж',
    category: 'metizy-i-antivandal',
    x: 70,
    y: 19,
    alignRight: true,
    hue: '#ff5d7a',
  },
  {
    id: 'complex',
    title: 'Игровой комплекс',
    category: 'krepleniya-i-podvesy',
    x: 54,
    y: 23,
    hue: '#2b8bff',
  },
  {
    id: 'slide',
    title: 'Горка',
    category: 'gorki-i-elementy',
    x: 62,
    y: 31,
    alignRight: true,
    hue: '#ff8a3d',
  },
  {
    id: 'rope-net',
    title: 'Канатная сеть',
    category: 'kanaty-i-seti',
    x: 45,
    y: 34,
    hue: '#37c66b',
  },
  {
    id: 'climbing',
    title: 'Стенка для лазания',
    category: 'plastikovye-detali',
    x: 78,
    y: 42,
    hue: '#ff4d4d',
  },
  {
    id: 'grips',
    title: 'Зацепы скалодрома',
    category: 'plastikovye-detali',
    x: 53,
    y: 54,
    alignRight: true,
    hue: '#00c2c7',
  },
  {
    id: 'swings',
    title: 'Качели',
    category: 'sidenya-kachelej',
    x: 13,
    y: 58,
    alignRight: true,
    hue: '#ffc247',
  },
  {
    id: 'carousel',
    title: 'Карусель',
    category: 'vtulki-i-gilzy',
    x: 41,
    y: 66,
    alignRight: true,
    hue: '#ff7a1a',
  },
  {
    id: 'seesaw',
    title: 'Балансир',
    category: 'soediniteli-i-furnitura',
    x: 78,
    y: 73,
    alignRight: true,
    hue: '#2fbf4f',
  },
  {
    id: 'mounts',
    title: 'Крепления',
    category: 'krepleniya-i-podvesy',
    x: 80,
    y: 85,
    hue: '#8fa3b8',
  },
] as const;

export type ResolvedHotspot = HotspotConfig & {
  /** Подпись на снимке — название узла площадки, а не раздела. */
  name: string;
  /** Раздел, куда ведёт точка. null — такого раздела в каталоге нет. */
  categoryName: string | null;
  href: string;
  /** null — категории нет в каталоге, счётчик не показываем. */
  productCount: number | null;
};

/**
 * Сопоставляет точки с деревом категорий.
 *
 * Подписью служит название узла («Крыша», «Горка»), а не раздела:
 * несколько узлов ведут в один раздел, и по названию раздела плашки
 * оказались бы одинаковыми — на снимке трижды повторялось бы
 * «Пластиковые детали».
 *
 * Если категории с таким slug нет (каталог ещё не наполнен), точка
 * ведёт в каталог с поиском по своей подписи — рабочая ссылка вместо
 * битой.
 */
export function resolveHotspots(categories: CategoryNode[]): ResolvedHotspot[] {
  return HOTSPOTS.map((spot) => {
    const category = findCategory(categories, spot.category);
    if (!category) {
      return {
        ...spot,
        name: spot.title,
        categoryName: null,
        href: catalogHref({ search: spot.title }),
        productCount: null,
      };
    }
    return {
      ...spot,
      name: spot.title,
      categoryName: category.name,
      href: catalogHref({ category: category.slug }),
      productCount: category.product_count ?? null,
    };
  });
}
