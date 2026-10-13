import type { Metadata } from 'next';

import { QuickOrderButton } from '@/components/quick-order/QuickOrderButton';
import { ButtonLink } from '@/components/ui/Button';
import { Breadcrumbs } from '@/components/ui/Breadcrumbs';
import { EmptyState } from '@/components/ui/States';
import { fetchFaq } from '@/lib/api/content';
import { metadataFromSeo } from '@/lib/seo';
import styles from '@/components/content/Page.module.css';

export async function generateMetadata(): Promise<Metadata> {
  const faq = await fetchFaq();
  return metadataFromSeo(faq?.seo, {
    title: 'Частые вопросы',
    description: 'Ответы о минимальных партиях, сертификатах, сроках и нестандартных размерах.',
    path: '/faq',
  });
}

export default async function FaqPage() {
  const faq = await fetchFaq();
  const items = faq?.items ?? [];

  return (
    <div className={`container ${styles.page}`}>
      <Breadcrumbs items={[{ href: '/', label: 'Главная' }, { label: 'Вопросы' }]} />

      <header className={styles.header}>
        <h1 className={styles.title}>Частые вопросы</h1>
        <p className={styles.lead}>
          Если ответа на ваш вопрос здесь нет — напишите нам, отвечаем в рабочее время.
        </p>
      </header>

      <section className={styles.section}>
        {items.length === 0 ? (
          <EmptyState
            title="Вопросы пока не добавлены"
            text="Раздел заполняется в админке."
            action={<ButtonLink href="/contacts">Задать вопрос</ButtonLink>}
          />
        ) : (
          <ul className={styles.faq}>
            {items.map((item, index) => (
              <li key={item.question}>
                {/* <details> — родная раскрывающаяся секция браузера:
                    работает без JS и правильно читается вслух. */}
                <details className={styles.faqItem} open={index === 0}>
                  <summary className={styles.faqQuestion}>{item.question}</summary>
                  <p className={styles.faqAnswer}>{item.answer}</p>
                </details>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className={styles.cta}>
        <div className={styles.ctaText}>
          <p className={styles.ctaTitle}>Остались вопросы по подбору?</p>
          <p className={styles.ctaSubtitle}>
            Пришлите спецификацию или фото узла — подберём комплектующие и посчитаем стоимость.
          </p>
        </div>
        <div className={styles.ctaActions}>
          <QuickOrderButton size="lg" options={{ mode: 'QUOTE' }}>
            Отправить спецификацию
          </QuickOrderButton>
          <ButtonLink href="/contacts" size="lg" variant="onDark">
            Контакты
          </ButtonLink>
        </div>
      </section>
    </div>
  );
}
