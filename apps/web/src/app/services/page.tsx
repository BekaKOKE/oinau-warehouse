import type { Metadata } from 'next';

import { QuickOrderButton } from '@/components/quick-order/QuickOrderButton';
import { ServiceList } from '@/components/services/ServiceList';
import { ButtonLink } from '@/components/ui/Button';
import { Breadcrumbs } from '@/components/ui/Breadcrumbs';
import { EmptyState } from '@/components/ui/States';
import { fetchContacts, fetchServices } from '@/lib/api/content';
import { metadataFromSeo } from '@/lib/seo';
import styles from '@/components/content/Page.module.css';

export async function generateMetadata(): Promise<Metadata> {
  const services = await fetchServices();
  return metadataFromSeo(services?.seo, {
    title: 'Услуги',
    description: 'Обжимка и обрезка канатов, металлорезка и подбор комплектующих по спецификации.',
    path: '/services',
  });
}

export default async function ServicesPage() {
  const [services, contacts] = await Promise.all([fetchServices(), fetchContacts()]);
  const items = services?.items ?? [];

  return (
    <div className={`container ${styles.page}`}>
      <Breadcrumbs items={[{ href: '/', label: 'Главная' }, { label: 'Услуги' }]} />

      <header className={styles.header}>
        <h1 className={styles.title}>Услуги</h1>
        {services?.intro ? <p className={styles.lead}>{services.intro}</p> : null}
      </header>

      {items.length > 0 ? (
        <ServiceList items={items} whatsappUrl={contacts?.whatsapp?.url ?? null} />
      ) : (
        <section className={styles.section}>
          <EmptyState
            title="Раздел пока не заполнен"
            text="Список услуг появится после заполнения раздела в админке. Уточнить, что мы можем сделать под ваш проект, можно у менеджера."
            action={<ButtonLink href="/contacts">Связаться с нами</ButtonLink>}
          />
        </section>
      )}

      <section className={styles.cta}>
        <div className={styles.ctaText}>
          <p className={styles.ctaTitle}>Работа по спецификации или чертежу</p>
          <p className={styles.ctaSubtitle}>
            Пришлите спецификацию проекта — рассчитаем комплектующие и услуги одним предложением.
          </p>
        </div>
        <div className={styles.ctaActions}>
          <QuickOrderButton size="lg" options={{ mode: 'QUOTE' }}>
            Отправить спецификацию
          </QuickOrderButton>
          <ButtonLink href="/catalog" size="lg" variant="onDark">
            Открыть каталог
          </ButtonLink>
        </div>
      </section>
    </div>
  );
}
