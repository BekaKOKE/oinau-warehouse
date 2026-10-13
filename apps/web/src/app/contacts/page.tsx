import type { Metadata } from 'next';

import { QuickOrderButton } from '@/components/quick-order/QuickOrderButton';
import { ButtonLink } from '@/components/ui/Button';
import { Breadcrumbs } from '@/components/ui/Breadcrumbs';
import { EmptyState } from '@/components/ui/States';
import { fetchContacts } from '@/lib/api/content';
import { metadataFromSeo } from '@/lib/seo';
import styles from '@/components/content/Page.module.css';

export async function generateMetadata(): Promise<Metadata> {
  const contacts = await fetchContacts();
  return metadataFromSeo(contacts?.seo, {
    title: 'Контакты',
    description: 'Адрес склада, телефоны, почта и реквизиты OINAU PRO.',
    path: '/contacts',
  });
}

export default async function ContactsPage() {
  const contacts = await fetchContacts();
  const requisites = contacts?.requisites;

  const requisiteRows: Array<[string, string | null | undefined]> = [
    ['Наименование', requisites?.company_name],
    ['БИН', requisites?.bin],
    ['IBAN', requisites?.iban],
    ['Банк', requisites?.bank_name],
    ['БИК', requisites?.bik],
    ['КБе', requisites?.kbe],
    ['Юридический адрес', requisites?.legal_address],
  ];
  const filledRequisites = requisiteRows.filter(([, value]) => Boolean(value));

  return (
    <div className={`container ${styles.page}`}>
      <Breadcrumbs items={[{ href: '/', label: 'Главная' }, { label: 'Контакты' }]} />

      <header className={styles.header}>
        <h1 className={styles.title}>Контакты</h1>
        {contacts?.working_hours ? <p className={styles.lead}>{contacts.working_hours}</p> : null}
      </header>

      {!contacts ? (
        <section className={styles.section}>
          <EmptyState
            title="Контакты пока не заполнены"
            text="Раздел заполняется в админке. Пока можно написать нам в WhatsApp — кнопка в правом нижнем углу."
          />
        </section>
      ) : (
        <>
          <section className={styles.section}>
            <div className={styles.cards}>
              {contacts.phones?.length ? (
                <div className={styles.card}>
                  <h2 className={styles.cardTitle}>Телефоны</h2>
                  <ul className={styles.contactList} style={{ marginTop: 'var(--space-3)' }}>
                    {contacts.phones.map((phone) => (
                      <li key={phone.tel}>
                        {phone.label ? (
                          <span className={styles.contactLabel}>{phone.label}</span>
                        ) : null}
                        <a className={styles.contactValue} href={`tel:${phone.tel}`}>
                          {phone.display}
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {contacts.emails?.length ? (
                <div className={styles.card}>
                  <h2 className={styles.cardTitle}>Почта</h2>
                  <ul className={styles.contactList} style={{ marginTop: 'var(--space-3)' }}>
                    {contacts.emails.map((email) => (
                      <li key={email.email}>
                        {email.label ? (
                          <span className={styles.contactLabel}>{email.label}</span>
                        ) : null}
                        <a className={styles.contactValue} href={`mailto:${email.email}`}>
                          {email.email}
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {contacts.address ? (
                <div className={styles.card}>
                  <h2 className={styles.cardTitle}>Склад и офис</h2>
                  <p className={styles.cardText}>{contacts.address}</p>
                  {contacts.map ? (
                    <p className={styles.cardText}>
                      <a
                        href={`https://yandex.ru/maps/?pt=${contacts.map.longitude},${contacts.map.latitude}&z=17&l=map`}
                        target="_blank"
                        rel="noreferrer noopener"
                      >
                        Открыть на карте →
                      </a>
                    </p>
                  ) : null}
                </div>
              ) : null}

              {contacts.whatsapp ? (
                <div className={styles.card}>
                  <h2 className={styles.cardTitle}>WhatsApp</h2>
                  <p className={styles.cardText}>
                    Пришлите спецификацию или фото узла — подберём комплектующие.
                  </p>
                  <p style={{ marginTop: 'var(--space-3)' }}>
                    <a
                      className={styles.contactValue}
                      href={contacts.whatsapp.url}
                      target="_blank"
                      rel="noreferrer noopener"
                    >
                      {contacts.whatsapp.display}
                    </a>
                  </p>
                </div>
              ) : null}
            </div>
          </section>

          {filledRequisites.length > 0 ? (
            <section className={styles.section} id="requisites" aria-labelledby="requisites-title">
              <h2 className={styles.sectionTitle} id="requisites-title">
                Реквизиты
              </h2>
              <table className={styles.requisites}>
                <tbody>
                  {filledRequisites.map(([label, value]) => (
                    <tr key={label}>
                      <th scope="row">{label}</th>
                      <td>{value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          ) : null}
        </>
      )}

      <section className={styles.cta}>
        <div className={styles.ctaText}>
          <p className={styles.ctaTitle}>Нужна позиция, которой нет в каталоге?</p>
          <p className={styles.ctaSubtitle}>
            Пришлите спецификацию или опишите задачу — подготовим коммерческое предложение с
            вариантами и ценой.
          </p>
        </div>
        <div className={styles.ctaActions}>
          <QuickOrderButton size="lg" options={{ mode: 'QUOTE' }}>
            Запросить КП
          </QuickOrderButton>
          <ButtonLink href="/catalog" size="lg" variant="onDark">
            Перейти в каталог
          </ButtonLink>
        </div>
      </section>
    </div>
  );
}
