/**
 * Остальные секции главной: популярные позиции, преимущества
 * и текст о компании. Тексты преимуществ и «о компании» — из CMS, без
 * неё блоки просто не выводятся.
 */

import Link from 'next/link';

import type { HomeContent, ProductListItem } from '@oinau/api-types';

import { ProductGrid } from '@/components/catalog/ProductGrid';
import styles from './Sections.module.css';

export function FeaturedProducts({ products }: { products: ProductListItem[] }) {
  if (products.length === 0) return null;

  return (
    <section className={`container ${styles.section}`} aria-labelledby="featured-title">
      <div className={styles.head} data-reveal>
        <h2 className={styles.title} id="featured-title">
          Часто заказывают
        </h2>
        <Link href="/catalog" className={styles.headLink}>
          Смотреть все <span aria-hidden="true">→</span>
        </Link>
      </div>
      <div data-reveal>
        <ProductGrid products={products} />
      </div>
    </section>
  );
}

/**
 * Преимущества — полоса ячеек через разделитель, как блок показателей
 * в макете. Сами тексты — из CMS.
 */
export function Advantages({ content }: { content: HomeContent | null }) {
  const items = content?.advantages ?? [];
  if (items.length === 0) return null;

  return (
    <section className={`container ${styles.section}`} aria-labelledby="advantages-title">
      <div className={styles.head} data-reveal>
        <h2 className={styles.title} id="advantages-title">
          Почему с нами работают
        </h2>
      </div>
      <ul className={styles.advantages} data-reveal>
        {items.map((item, index) => (
          <li key={item.title} className={styles.advantage}>
            <span className={styles.advantageIndex} aria-hidden="true">
              {String(index + 1).padStart(2, '0')}
            </span>
            <h3 className={styles.advantageTitle}>{item.title}</h3>
            {item.text ? <p className={styles.advantageText}>{item.text}</p> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function AboutBlock({ content }: { content: HomeContent | null }) {
  const about = content?.about;
  if (!about) return null;

  return (
    <section className={`container ${styles.section}`} aria-labelledby="about-title">
      <div className={styles.about} data-reveal>
        <div className={styles.aboutMain}>
          <p className={styles.eyebrow}>О компании</p>
          <h2 className={styles.aboutTitle} id="about-title">
            {about.title ?? 'О компании'}
          </h2>
          <p className={styles.aboutText}>{about.text}</p>
        </div>
        <div className={styles.aboutActions}>
          <Link href="/catalog" className={styles.aboutLink}>
            Перейти в каталог <span aria-hidden="true">→</span>
          </Link>
          <Link href="/contacts" className={styles.aboutLink}>
            Контакты и реквизиты <span aria-hidden="true">→</span>
          </Link>
          <Link href="/delivery" className={styles.aboutLink}>
            Доставка и оплата <span aria-hidden="true">→</span>
          </Link>
        </div>
      </div>
    </section>
  );
}
