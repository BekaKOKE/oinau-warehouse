/**
 * Остальные секции главной: промо-блоки, преимущества и текст
 * о компании. Тексты — из CMS, без неё блоки просто не выводятся.
 */

import Link from 'next/link';

import type { HomeContent, ProductListItem } from '@oinau/api-types';

import { ProductGrid } from '@/components/catalog/ProductGrid';
import styles from './Sections.module.css';

export function PromoCards() {
  return (
    <section className={styles.section} aria-label="Сервисы для профессионалов">
      <div className={styles.promoGrid}>
        <article className={`${styles.promo} ${styles.promoDark}`}>
          <div>
            <p className={styles.promoEyebrow}>Доставка по Казахстану</p>
            <h3 className={styles.promoTitle}>Со склада в Алматы за 24 часа</h3>
            <p className={styles.promoText}>
              Ходовые позиции всегда в наличии, крупногабарит — транспортными компаниями.
            </p>
          </div>
          <Link href="/delivery" className={styles.promoLink}>
            Условия доставки →
          </Link>
        </article>

        <article className={styles.promo}>
          <div>
            <p className={styles.promoEyebrow}>Для проектировщиков</p>
            <h3 className={styles.promoTitle}>Характеристики и документы</h3>
            <p className={styles.promoText}>
              Размеры, материалы и сертификаты — в карточке каждой позиции.
            </p>
          </div>
          <Link href="/catalog" className={styles.promoLink}>
            Перейти в каталог →
          </Link>
        </article>

        <article className={styles.promo}>
          <div>
            <p className={styles.promoEyebrow}>B2B</p>
            <h3 className={styles.promoTitle}>Оптовые условия и спецификации</h3>
            <p className={styles.promoText}>
              Цена от объёма, отсрочка платежа, подбор аналогов по вашей спецификации.
            </p>
          </div>
          <Link href="/contacts" className={styles.promoLink}>
            Получить прайс →
          </Link>
        </article>
      </div>
    </section>
  );
}

export function FeaturedProducts({ products }: { products: ProductListItem[] }) {
  if (products.length === 0) return null;

  return (
    <section className={styles.section} aria-labelledby="featured-title">
      <div className={styles.head}>
        <h2 className={styles.title} id="featured-title">
          Чаще всего заказывают
        </h2>
        <Link href="/catalog" className={styles.headLink}>
          В каталог →
        </Link>
      </div>
      <div style={{ marginTop: 'var(--space-5)' }}>
        <ProductGrid products={products} />
      </div>
    </section>
  );
}

export function Advantages({ content }: { content: HomeContent | null }) {
  const items = content?.advantages ?? [];
  if (items.length === 0) return null;

  return (
    <section className={styles.section} aria-labelledby="advantages-title">
      <h2 className={styles.title} id="advantages-title">
        Почему с нами работают
      </h2>
      <ul className={styles.advantages}>
        {items.map((item) => (
          <li key={item.title} className={styles.advantage}>
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
    <section className={`${styles.section} ${styles.sectionLast}`} aria-labelledby="about-title">
      <div className={styles.about}>
        <h2 className={styles.aboutTitle} id="about-title">
          {about.title ?? 'О компании'}
        </h2>
        <p className={styles.aboutText}>{about.text}</p>
      </div>
    </section>
  );
}
