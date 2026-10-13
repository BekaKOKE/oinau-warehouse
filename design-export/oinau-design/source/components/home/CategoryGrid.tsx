/**
 * Секция «Категории комплектующих».
 *
 * Категории приходят из `/api/v1/public/categories`. Каталог в разметке
 * не хардкодится: добавление раздела в админке должно менять главную
 * без пересборки фронтенда.
 */

import Link from 'next/link';

import type { CategoryNode } from '@oinau/api-types';

import { EmptyState } from '@/components/ui/States';
import { productCountLabel } from '@/lib/format';
import styles from './Sections.module.css';

// Цвета плиток из макета: раздел узнаётся по цвету, а не только по тексту.
const TILE_HUES = [
  '#1f8f4d',
  '#0b5fd0',
  '#c2451f',
  '#7b52c9',
  '#d1820a',
  '#0e8f96',
  '#c23a72',
  '#3f5a78',
] as const;

/** Короткая метка на плитке: первое слово названия. */
function tileLabel(name: string): string {
  const word = name.split(/[\s,/]+/)[0] ?? name;
  return word.length > 9 ? `${word.slice(0, 8)}.` : word;
}

export function CategoryGrid({
  categories,
  totalProducts,
}: {
  categories: CategoryNode[];
  totalProducts: number;
}) {
  // Показываем подразделы корня: верхний уровень обычно один
  // («Комплектующие»), и сетка из одной карточки бессмысленна.
  const items = categories.some((node) => (node.children ?? []).length > 0)
    ? categories.flatMap((node) => node.children ?? [])
    : categories;

  return (
    <section className={styles.section} aria-labelledby="categories-title">
      <div className={styles.head}>
        <h2 className={styles.title} id="categories-title">
          Категории комплектующих
        </h2>
        <Link href="/catalog" className={styles.headLink}>
          {totalProducts > 0 ? `Все ${productCountLabel(totalProducts)} →` : 'В каталог →'}
        </Link>
      </div>

      {items.length === 0 ? (
        <div style={{ marginTop: 'var(--space-5)' }}>
          <EmptyState
            title="Каталог ещё наполняется"
            text="Разделы появятся, как только каталог будет загружен."
          />
        </div>
      ) : (
        <div className={styles.grid}>
          {items.map((category, index) => {
            const hue = TILE_HUES[index % TILE_HUES.length] ?? TILE_HUES[1];
            return (
              <Link
                key={category.slug}
                href={`/catalog/${category.slug}`}
                className={styles.category}
              >
                <span
                  className={styles.categoryTile}
                  style={{
                    color: hue,
                    background: `${hue}1c`,
                    border: `1px solid ${hue}3d`,
                  }}
                  aria-hidden="true"
                >
                  {tileLabel(category.name)}
                </span>
                <span className={styles.categoryBody}>
                  <span className={styles.categoryName}>{category.name}</span>
                  <span className={styles.categoryMeta}>
                    {productCountLabel(category.product_count ?? 0)}
                  </span>
                </span>
              </Link>
            );
          })}
        </div>
      )}
    </section>
  );
}
