/**
 * Вкладки разделов над выдачей. Отдельные маршруты (`/catalog/<slug>`),
 * а не параметр запроса: у раздела должен быть свой адрес, заголовок
 * и мета-описание.
 */

import Link from 'next/link';

import type { CategoryNode } from '@oinau/api-types';

import { formatCount } from '@/lib/format';
import styles from './Catalog.module.css';

export function CategoryTabs({
  categories,
  activeSlug,
  totalProducts,
}: {
  categories: CategoryNode[];
  activeSlug?: string;
  totalProducts: number;
}) {
  const items = categories.some((node) => (node.children ?? []).length > 0)
    ? categories.flatMap((node) => node.children ?? [])
    : categories;

  if (items.length === 0) return null;

  return (
    <nav className={styles.tabs} aria-label="Разделы каталога">
      <Link
        href="/catalog"
        className={`${styles.tab} ${activeSlug ? '' : styles.tabActive}`}
        aria-current={activeSlug ? undefined : 'page'}
      >
        Все категории
        <span className={styles.tabCount}>{formatCount(totalProducts)}</span>
      </Link>
      {items.map((category) => (
        <Link
          key={category.slug}
          href={`/catalog/${category.slug}`}
          className={`${styles.tab} ${category.slug === activeSlug ? styles.tabActive : ''}`}
          aria-current={category.slug === activeSlug ? 'page' : undefined}
        >
          {category.name}
          <span className={styles.tabCount}>{formatCount(category.product_count ?? 0)}</span>
        </Link>
      ))}
    </nav>
  );
}
