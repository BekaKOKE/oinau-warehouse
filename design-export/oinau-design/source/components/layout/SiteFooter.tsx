/**
 * Подвал. Контакты и реквизиты берутся из CMS: держать адрес и БИН
 * в двух местах — верный способ обновить только одно из них.
 */

import Link from 'next/link';

import type { CategoryNode, ContactsContent, SiteSettings } from '@oinau/api-types';

import { SITE_NAME, SITE_TAGLINE } from '@/lib/config';
import { NAV_LINKS } from '@/lib/navigation';
import styles from './SiteFooter.module.css';

const SOCIAL_LABELS: Record<string, string> = {
  INSTAGRAM: 'Instagram',
  TELEGRAM: 'Telegram',
  WHATSAPP: 'WhatsApp',
  FACEBOOK: 'Facebook',
  YOUTUBE: 'YouTube',
  TIKTOK: 'TikTok',
  VK: 'VK',
};

export function SiteFooter({
  settings,
  contacts,
  categories,
}: {
  settings: SiteSettings | null;
  contacts: ContactsContent | null;
  categories: CategoryNode[];
}) {
  const name = settings?.site_name ?? SITE_NAME;
  const sections = categories.flatMap((node) => node.children ?? []).slice(0, 6);
  const requisites = contacts?.requisites;
  const year = new Date().getFullYear();

  return (
    <footer className={styles.footer}>
      <div className={styles.inner}>
        <div className={styles.brand}>
          <span className={styles.brandName}>
            {name === SITE_NAME ? (
              <>
                OINAU<span> PRO</span>
              </>
            ) : (
              name
            )}
          </span>
          <p className={styles.brandText}>
            {SITE_TAGLINE}. Поставки для производителей, монтажных организаций и муниципальных
            проектов.
          </p>
          {contacts?.working_hours ? (
            <p className={styles.brandText}>{contacts.working_hours}</p>
          ) : null}
        </div>

        {sections.length > 0 ? (
          <nav className={styles.column} aria-label="Разделы каталога">
            <span className={styles.columnTitle}>Каталог</span>
            {sections.map((category) => (
              <Link key={category.slug} href={`/catalog/${category.slug}`} className={styles.link}>
                {category.name}
              </Link>
            ))}
          </nav>
        ) : null}

        <nav className={styles.column} aria-label="Информация">
          <span className={styles.columnTitle}>Покупателям</span>
          {NAV_LINKS.map((link) => (
            <Link key={link.href} href={link.href} className={styles.link}>
              {link.label}
            </Link>
          ))}
          <Link href="/favorites" className={styles.link}>
            Избранное
          </Link>
        </nav>

        <address className={styles.column} style={{ fontStyle: 'normal' }}>
          <span className={styles.columnTitle}>Контакты</span>
          {contacts?.phones?.map((phone) => (
            <a key={phone.tel} href={`tel:${phone.tel}`} className={styles.link}>
              {phone.display}
              {phone.label ? ` — ${phone.label}` : ''}
            </a>
          ))}
          {contacts?.emails?.map((email) => (
            <a key={email.email} href={`mailto:${email.email}`} className={styles.link}>
              {email.email}
            </a>
          ))}
          {contacts?.address ? <span className={styles.value}>{contacts.address}</span> : null}
          {settings?.social_links?.length ? (
            <span className={styles.value}>
              {settings.social_links.map((social) => (
                <a
                  key={social.network}
                  href={social.url}
                  className={styles.link}
                  target="_blank"
                  rel="noreferrer noopener"
                  style={{ marginRight: 12 }}
                >
                  {SOCIAL_LABELS[social.network] ?? social.network}
                </a>
              ))}
            </span>
          ) : null}
        </address>
      </div>

      <div className={styles.bottom}>
        <div className={styles.bottomInner}>
          <span>
            © {year} {name}
          </span>
          {requisites ? (
            <span className={styles.requisites}>
              {requisites.company_name ? <span>{requisites.company_name}</span> : null}
              {requisites.bin ? <span>БИН {requisites.bin}</span> : null}
            </span>
          ) : null}
        </div>
      </div>
    </footer>
  );
}
