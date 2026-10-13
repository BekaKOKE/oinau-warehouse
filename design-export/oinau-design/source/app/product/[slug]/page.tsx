import type { Metadata } from 'next';
import { notFound } from 'next/navigation';

import { ProductGrid } from '@/components/catalog/ProductGrid';
import { ImageGallery } from '@/components/product/ImageGallery';
import { OrderPanel } from '@/components/product/OrderPanel';
import { AvailabilityBadge } from '@/components/ui/AvailabilityBadge';
import { Breadcrumbs, type Crumb } from '@/components/ui/Breadcrumbs';
import { fetchProduct, fetchRelatedProducts } from '@/lib/api/catalog';
import {
  currencySymbol,
  describePrice,
  formatAmount,
  formatTierRange,
  unitLabel,
} from '@/lib/format';
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

export default async function ProductPage({ params }: PageProps) {
  const { slug } = await params;
  const product = await fetchProduct(slug);
  if (!product) notFound();

  const related = await fetchRelatedProducts(slug);
  const price = describePrice(product.price, product.unit);
  const symbol = currencySymbol(product.price.currency);
  const tiers = product.price.tiers ?? [];
  const characteristics = product.characteristics ?? [];
  const categories = product.categories ?? [];
  // `specs` в схеме — свободная карта строк; приводим значения к строке
  // явно, чтобы в разметку не попал `unknown`.
  const specs: Array<[string, string]> = Object.entries(product.specs ?? {}).map(([key, value]) => [
    key,
    String(value),
  ]);

  const crumbs: Crumb[] = [
    { href: '/', label: 'Главная' },
    { href: '/catalog', label: 'Каталог' },
    ...(product.breadcrumbs ?? []).map((item) => ({
      href: `/catalog/${item.slug}`,
      label: item.name,
    })),
    { label: product.name },
  ];

  return (
    <div className={styles.page}>
      <Breadcrumbs items={crumbs} />

      <div className={styles.top}>
        <ImageGallery images={product.images ?? []} sku={product.sku} name={product.name} />

        <div className={styles.summary}>
          <h1 className={styles.title}>{product.name}</h1>

          <div className={styles.metaRow}>
            <span className={styles.sku}>Артикул {product.sku}</span>
            <AvailabilityBadge value={product.availability} />
          </div>

          {product.short_description ? (
            <p className={styles.lead}>{product.short_description}</p>
          ) : null}

          <div className={styles.priceBlock}>
            {price.onRequest ? (
              <>
                <p className={styles.priceValue} style={{ fontSize: 22 }}>
                  Цена по запросу
                </p>
                <p className={styles.priceNote}>
                  Стоимость зависит от объёма и исполнения — рассчитаем в ответ на заявку.
                </p>
              </>
            ) : (
              <>
                <p className={styles.priceMain}>
                  {price.prefix ? <span className={styles.priceFrom}>{price.prefix}</span> : null}
                  <span className={styles.priceValue}>{price.amount}</span>
                  <span className={styles.priceUnit}>{price.suffix}</span>
                </p>
                {product.price.type === 'TIERED' ? (
                  <p className={styles.priceNote}>Цена снижается с объёмом — см. таблицу ниже.</p>
                ) : null}
              </>
            )}
          </div>

          <OrderPanel product={product} />

          <dl className={styles.facts}>
            <div className={styles.fact}>
              <dt className={styles.factLabel}>Единица</dt>
              <dd className={styles.factValue}>{unitLabel(product.unit)}</dd>
            </div>
            {product.brand ? (
              <div className={styles.fact}>
                <dt className={styles.factLabel}>Бренд</dt>
                <dd className={styles.factValue}>{product.brand}</dd>
              </div>
            ) : null}
            {categories.length > 0 ? (
              <div className={styles.fact}>
                <dt className={styles.factLabel}>Раздел</dt>
                <dd className={styles.factValue}>{categories[0]?.name}</dd>
              </div>
            ) : null}
          </dl>
        </div>
      </div>

      <div className={styles.blocks}>
        {product.description ? (
          <section className={styles.block} aria-labelledby="description-title">
            <h2 className={styles.blockTitle} id="description-title">
              Описание
            </h2>
            <p className={styles.description}>{product.description}</p>
          </section>
        ) : null}

        {characteristics.length > 0 || specs.length > 0 ? (
          <section className={styles.block} aria-labelledby="specs-title">
            <h2 className={styles.blockTitle} id="specs-title">
              Характеристики
            </h2>
            <table className={styles.specTable}>
              <tbody>
                {characteristics.map((item) => (
                  <tr key={item.code}>
                    <th scope="row">{item.name}</th>
                    <td>{item.value}</td>
                  </tr>
                ))}
                {specs.map(([key, value]) => (
                  <tr key={key}>
                    <th scope="row">{key}</th>
                    <td>{value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        ) : null}

        {tiers.length > 0 ? (
          <section className={styles.block} aria-labelledby="tiers-title">
            <h2 className={styles.blockTitle} id="tiers-title">
              Цена от объёма
            </h2>
            <table className={styles.tiers}>
              <thead>
                <tr>
                  <th scope="col">Количество, {unitLabel(product.unit)}</th>
                  <th scope="col" style={{ textAlign: 'right' }}>
                    Цена за {unitLabel(product.unit)}
                  </th>
                </tr>
              </thead>
              <tbody>
                {tiers.map((tier) => (
                  <tr key={`${tier.min_quantity}-${tier.price}`}>
                    <td className={styles.tierQty}>
                      {formatTierRange(tier.min_quantity, tier.max_quantity)}
                    </td>
                    <td className={styles.tierPrice}>
                      {formatAmount(tier.price)} {symbol}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        ) : null}
      </div>

      {related.length > 0 ? (
        <section className={styles.related} aria-labelledby="related-title">
          <h2 className={styles.relatedTitle} id="related-title">
            Похожие позиции
          </h2>
          <ProductGrid products={related} />
        </section>
      ) : null}
    </div>
  );
}
