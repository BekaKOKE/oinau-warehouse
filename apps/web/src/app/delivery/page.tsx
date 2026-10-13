import type { Metadata } from 'next';

import { QuickOrderButton } from '@/components/quick-order/QuickOrderButton';
import { ButtonLink } from '@/components/ui/Button';
import { Breadcrumbs } from '@/components/ui/Breadcrumbs';
import { EmptyState } from '@/components/ui/States';
import { fetchDelivery } from '@/lib/api/content';
import { metadataFromSeo } from '@/lib/seo';
import styles from '@/components/content/Page.module.css';

export async function generateMetadata(): Promise<Metadata> {
  const delivery = await fetchDelivery();
  return metadataFromSeo(delivery?.seo, {
    title: 'Доставка и оплата',
    description: 'Условия доставки комплектующих по Алматы и Казахстану, способы оплаты.',
    path: '/delivery',
  });
}

export default async function DeliveryPage() {
  const delivery = await fetchDelivery();
  const methods = delivery?.methods ?? [];

  return (
    <div className={`container ${styles.page}`}>
      <Breadcrumbs items={[{ href: '/', label: 'Главная' }, { label: 'Доставка и оплата' }]} />

      <header className={styles.header}>
        <h1 className={styles.title}>Доставка и оплата</h1>
        {delivery?.intro ? <p className={styles.lead}>{delivery.intro}</p> : null}
      </header>

      {methods.length > 0 ? (
        <section className={styles.section} aria-labelledby="delivery-methods">
          <h2 className={styles.sectionTitle} id="delivery-methods">
            Способы доставки
          </h2>
          <div className={styles.cards}>
            {methods.map((method) => (
              <article key={method.title} className={styles.card}>
                <h3 className={styles.cardHeading}>{method.title}</h3>
                {method.text ? <p className={styles.cardText}>{method.text}</p> : null}
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {delivery?.payment ? (
        <section className={styles.section} aria-labelledby="delivery-payment">
          <h2 className={styles.sectionTitle} id="delivery-payment">
            Оплата
          </h2>
          <div className={styles.card}>
            <p className={styles.cardText}>{delivery.payment}</p>
          </div>
        </section>
      ) : null}

      {!delivery ? (
        <section className={styles.section}>
          <EmptyState
            title="Раздел пока не заполнен"
            text="Условия доставки появятся после заполнения раздела в админке. Уточнить их можно у менеджера."
            action={<ButtonLink href="/contacts">Связаться с нами</ButtonLink>}
          />
        </section>
      ) : null}

      <section className={styles.cta}>
        <div className={styles.ctaText}>
          <p className={styles.ctaTitle}>Рассчитать доставку под ваш объём</p>
          <p className={styles.ctaSubtitle}>
            Оставьте телефон или соберите корзину — менеджер посчитает стоимость доставки вместе с
            позициями.
          </p>
        </div>
        <div className={styles.ctaActions}>
          <QuickOrderButton size="lg">Быстрый заказ</QuickOrderButton>
          <ButtonLink href="/catalog" size="lg" variant="onDark">
            Открыть каталог
          </ButtonLink>
        </div>
      </section>
    </div>
  );
}
