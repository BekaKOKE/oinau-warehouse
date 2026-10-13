/**
 * Разделы каталога на главной.
 *
 * Категории приходят из `/api/v1/public/categories`. Каталог в разметке
 * не хардкодится: добавление раздела в админке меняет главную без
 * пересборки фронтенда.
 *
 * Обложка раздела — своя картинка из медиатеки, если её задали
 * в админке. Не задали — фото товара из этого же раздела (`previews`
 * собирает страница), а «от N ₸» — цена его самой дешёвой позиции.
 * Нет ни того, ни другого — спокойная плитка с номером раздела,
 * а не выдуманная картинка.
 */

import Image from 'next/image';
import Link from 'next/link';

import type { CategoryNode, ProductImage } from '@oinau/api-types';

import { EmptyState } from '@/components/ui/States';
import { thumbSource } from '@/components/ui/ProductImage';
import { currencySymbol, formatAmount, formatCount, plural } from '@/lib/format';
import styles from './Sections.module.css';

export type CategoryPreview = {
  image: ProductImage | null;
  fromPrice: string | null;
  currency: string;
};

export function CategoryGrid({
  categories,
  previews = {},
  totalProducts = 0,
  anchorId,
}: {
  categories: CategoryNode[];
  previews?: Record<string, CategoryPreview>;
  totalProducts?: number;
  anchorId?: string;
}) {
  // Показываем подразделы корня: верхний уровень обычно один
  // («Комплектующие»), и сетка из одной карточки бессмысленна.
  const items = categories.some((node) => (node.children ?? []).length > 0)
    ? categories.flatMap((node) => node.children ?? [])
    : categories;

  return (
    <section
      className={`container ${styles.section}`}
      id={anchorId}
      aria-labelledby="categories-title"
    >
      <div className={styles.head} data-reveal>
        <h2 className={styles.title} id="categories-title">
          Каталог
        </h2>
        {items.length > 0 ? (
          <span className={styles.headMeta}>
            {formatCount(items.length)} {plural(items.length, ['раздел', 'раздела', 'разделов'])}
            {totalProducts > 0
              ? ` · ${formatCount(totalProducts)} ${plural(totalProducts, ['позиция', 'позиции', 'позиций'])}`
              : ''}
          </span>
        ) : null}
        <Link href="/catalog" className={styles.headLink}>
          Весь каталог <span aria-hidden="true">→</span>
        </Link>
      </div>

      {items.length === 0 ? (
        <EmptyState
          title="Каталог ещё наполняется"
          text="Разделы появятся, как только каталог будет загружен."
        />
      ) : (
        <ul className={styles.categoryGrid}>
          {items.map((category, index) => {
            const count = category.product_count ?? 0;
            const preview = previews[category.slug];
            // Своя обложка важнее подставленного фото товара.
            const cover =
              category.image?.variants?.thumb ??
              category.image?.url ??
              (preview?.image ? thumbSource(preview.image) : null);
            return (
              <li
                key={category.slug}
                data-reveal
                style={{ '--reveal-delay': `${index * 50}ms` } as React.CSSProperties}
              >
                <Link href={`/catalog/${category.slug}`} className={styles.category}>
                  <span className={styles.categoryMedia} aria-hidden="true">
                    {cover ? (
                      <Image
                        src={cover}
                        alt=""
                        fill
                        sizes="(max-width: 560px) 50vw, (max-width: 1180px) 33vw, 300px"
                        className={styles.categoryImage}
                      />
                    ) : (
                      <span className={styles.categoryIndex}>
                        {String(index + 1).padStart(2, '0')}
                      </span>
                    )}
                  </span>
                  <span className={styles.categoryBody}>
                    <span className={styles.categoryName}>{category.name}</span>
                    <span className={styles.categoryMeta}>
                      <span>
                        {formatCount(count)} {plural(count, ['позиция', 'позиции', 'позиций'])}
                      </span>
                      {preview?.fromPrice ? (
                        <span className={styles.categoryPrice}>
                          от {formatAmount(preview.fromPrice)} {currencySymbol(preview.currency)}
                        </span>
                      ) : null}
                    </span>
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
