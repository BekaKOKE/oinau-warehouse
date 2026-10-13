import type { Metadata } from 'next';
import { notFound } from 'next/navigation';

import { ProductGrid } from '@/components/catalog/ProductGrid';
import { BuyBox } from '@/components/product/BuyBox';
import { ImageGallery } from '@/components/product/ImageGallery';
import { SchemeBlock } from '@/components/product/SchemeBlock';
import { AvailabilityBadge } from '@/components/ui/AvailabilityBadge';
import { Breadcrumbs, type Crumb } from '@/components/ui/Breadcrumbs';
import { fetchProduct, fetchRelatedProducts } from '@/lib/api/catalog';
import { unitLabel } from '@/lib/format';
import { productSections, type SpecRow } from '@/lib/product-sections';
import { buildMetadata } from '@/lib/seo';
import styles from '@/components/product/Product.module.css';

type PageProps = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const product = await fetchProduct(slug);
  if (!product) {
    return buildMetadata({ title: 'Товар не найден', path: `/product/${slug}`, noindex: true });
  }

  const main = product.images?.find((image) => image.is_main) ?? product.images?.[0];
  return buildMetadata({
    // Заголовок зависит от товара: «Канат армированный Ø16 мм — OINAU PRO».
    title: product.seo_title ?? product.name,
    description: product.seo_description ?? product.short_description ?? product.description,
    path: `/product/${slug}`,
    image: main?.url ?? null,
  });
}

function SpecList({ rows }: { rows: SpecRow[] }) {
  return (
    <dl className={styles.specs}>
      {rows.map((row) => (
        <div key={row.key} className={styles.spec}>
          <dt>{row.name}</dt>
          {/* Моноширинный — только для размеров и чисел; «Нержавеющая
              сталь» остаётся обычным текстом. */}
          <dd className={/\d/.test(row.value) ? undefined : styles.specText}>{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export default async function ProductPage({ params }: PageProps) {
  const { slug } = await params;
  const product = await fetchProduct(slug);
  if (!product) notFound();

  const related = await fetchRelatedProducts(slug);
  const documents = product.documents ?? [];
  const { color, characteristics, packaging } = productSections(product);

  const crumbs: Crumb[] = [
    { href: '/', label: 'Главная' },
    { href: '/catalog', label: 'Каталог' },
    ...(product.breadcrumbs ?? []).map((item) => ({
      href: `/catalog/${item.slug}`,
      label: item.name,
    })),
    { label: product.name },
  ];

  const unit = unitLabel(product.unit);
  // Описание показывается под карточкой; краткое — только если полного нет,
  // иначе один и тот же текст повторяется дважды.
  const description = product.description ?? product.short_description;
  const hasSpecs = characteristics.length > 0 || packaging.length > 0;

  return (
    <div className={`container ${styles.page}`}>
      <Breadcrumbs items={crumbs} />

      <h1 className={styles.title}>{product.name}</h1>

      <div className={styles.sheet}>
        <div className={styles.main}>
          <ImageGallery images={product.images ?? []} sku={product.sku} name={product.name} />

          <div className={styles.summary}>
            <p className={styles.sku}>
              Артикул: <span className={styles.skuValue}>{product.sku}</span>
            </p>

            <dl className={styles.keyFacts}>
              <div className={styles.keyFact}>
                <dt>Наличие</dt>
                <dd>
                  <AvailabilityBadge value={product.availability} />
                </dd>
              </div>
              {/* Цвет-характеристика не нужен, если цвет выбирается при заказе. */}
              {color && !product.colors?.length ? (
                <div className={styles.keyFact}>
                  <dt>Цвет</dt>
                  <dd>{color}</dd>
                </div>
              ) : null}
              <div className={styles.keyFact}>
                <dt>Единица</dt>
                <dd>{unit}</dd>
              </div>
              {product.brand ? (
                <div className={styles.keyFact}>
                  <dt>Бренд</dt>
                  <dd>{product.brand}</dd>
                </div>
              ) : null}
            </dl>

            <BuyBox product={product} />
          </div>
        </div>

        {description || hasSpecs ? (
          <div className={styles.details}>
            {description ? (
              <section className={styles.detailsDescription} aria-labelledby="description-title">
                <h2 className={styles.blockTitle} id="description-title">
                  Описание
                </h2>
                <p className={styles.description}>{description}</p>
              </section>
            ) : null}

            {hasSpecs ? (
              <div className={styles.specGroups}>
                {characteristics.length > 0 ? (
                  <section aria-labelledby="specs-title">
                    <h2 className={styles.blockTitle} id="specs-title">
                      Характеристики
                    </h2>
                    <SpecList rows={characteristics} />
                  </section>
                ) : null}

                {packaging.length > 0 ? (
                  <section aria-labelledby="packaging-title">
                    <h2 className={styles.blockTitle} id="packaging-title">
                      Упаковка
                    </h2>
                    <SpecList rows={packaging} />
                  </section>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      {documents.length > 0 ? (
        <div className={styles.blocks}>
          <SchemeBlock documents={documents} productName={product.name} />
        </div>
      ) : null}

      {related.length > 0 ? (
        <section className={styles.related} aria-labelledby="related-title">
          <div className={styles.relatedHead}>
            <h2 className={styles.relatedTitle} id="related-title">
              Похожие позиции
            </h2>
          </div>
          <ProductGrid products={related} />
        </section>
      ) : null}
    </div>
  );
}
