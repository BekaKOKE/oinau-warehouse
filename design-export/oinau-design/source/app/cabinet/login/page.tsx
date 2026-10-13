/**
 * Заглушка личного кабинета.
 *
 * Кабинет клиента — отдельный этап. Здесь честная страница-заглушка,
 * а не форма входа, которой некуда отправлять данные: неработающее
 * поле пароля хуже, чем прямое «пока недоступно».
 */

import type { Metadata } from 'next';

import { ButtonLink } from '@/components/ui/Button';
import { Breadcrumbs } from '@/components/ui/Breadcrumbs';
import { buildMetadata } from '@/lib/seo';
import styles from '@/components/content/Page.module.css';

export const metadata: Metadata = buildMetadata({
  title: 'Личный кабинет',
  description: 'Личный кабинет клиента OINAU PRO.',
  path: '/cabinet/login',
  noindex: true,
});

export default function CabinetLoginPage() {
  return (
    <div className={styles.page}>
      <Breadcrumbs items={[{ href: '/', label: 'Главная' }, { label: 'Личный кабинет' }]} />

      <header className={styles.header}>
        <h1 className={styles.title}>Личный кабинет скоро откроется</h1>
        <p className={styles.lead}>
          В кабинете появятся история заявок, счета, закрывающие документы и персональные цены. Пока
          заявку можно отправить без регистрации — менеджер ответит по указанным контактам.
        </p>
      </header>

      <section className={styles.section}>
        <div className={styles.cards}>
          <article className={styles.card}>
            <h2 className={styles.cardTitle}>Заявка без регистрации</h2>
            <p className={styles.cardText}>
              Соберите позиции в каталоге и отправьте заявку — ответим в рабочее время.
            </p>
          </article>
          <article className={styles.card}>
            <h2 className={styles.cardTitle}>Оптовые условия</h2>
            <p className={styles.cardText}>
              Цены от объёма и отсрочку платежа обсуждаем с менеджером по вашей спецификации.
            </p>
          </article>
        </div>
      </section>

      <section className={styles.cta}>
        <div className={styles.ctaText}>
          <p className={styles.ctaTitle}>Нужны цены и условия уже сейчас?</p>
          <p className={styles.ctaSubtitle}>Отправьте заявку из каталога или напишите нам.</p>
        </div>
        <ButtonLink href="/catalog" variant="light" size="lg">
          Перейти в каталог
        </ButtonLink>
      </section>
    </div>
  );
}
