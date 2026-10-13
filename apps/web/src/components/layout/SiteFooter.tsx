/**
 * Подвал. Контакты и реквизиты берутся из CMS: держать адрес и БИН
 * в двух местах — верный способ обновить только одно из них.
 *
 * Юридические данные не выдумываются: блок реквизитов и ссылка на них
 * появляются только если раздел заполнен в админке.
 */

import Image from 'next/image';
import Link from 'next/link';

import type { CategoryNode, ContactsContent, SiteSettings } from '@oinau/api-types';

import { QuickOrderButton } from '@/components/quick-order/QuickOrderButton';
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
  const whatsapp = contacts?.whatsapp ?? settings?.whatsapp ?? null;
  const socials = (settings?.social_links ?? []).filter((social) => social.network !== 'WHATSAPP');
  const [mainPhone, ...otherPhones] = contacts?.phones ?? [];
  const year = new Date().getFullYear();

  return (
    <footer className={styles.footer}>
      <div className={`container ${styles.inner}`}>
        <div className={styles.brand}>
          <Link href="/" className={styles.brandLink} aria-label={`${name} — на главную`}>
            <Image
              src="/brand/logo-white.png"
              alt=""
              width={1000}
              height={255}
              className={styles.brandLogo}
            />
          </Link>
          <p className={styles.brandText}>
            {SITE_TAGLINE}. Поставки для производителей, монтажных организаций и муниципальных
            проектов.
          </p>
          {whatsapp ? (
            <a
              href={whatsapp.url}
              className={styles.whatsapp}
              target="_blank"
              rel="noreferrer noopener"
            >
              <span className={styles.whatsappDot} aria-hidden="true" />
              WhatsApp · {whatsapp.display}
            </a>
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
            <Link href="/catalog" className={`${styles.link} ${styles.linkAccent}`}>
              Весь каталог →
            </Link>
          </nav>
        ) : null}

        <nav className={styles.column} aria-label="Клиентам">
          <span className={styles.columnTitle}>Клиентам</span>
          {NAV_LINKS.map((link) => (
            <Link key={link.href} href={link.href} className={styles.link}>
              {link.label}
            </Link>
          ))}
          <Link href="/favorites" className={styles.link}>
            Избранное
          </Link>
          <Link href="/cabinet/login" className={styles.link}>
            Личный кабинет
          </Link>
          {requisites ? (
            <Link href="/contacts#requisites" className={styles.link}>
              Реквизиты
            </Link>
          ) : null}
        </nav>

        <address className={styles.column}>
          <span className={styles.columnTitle}>Контакты</span>
          {mainPhone ? (
            <a href={`tel:${mainPhone.tel}`} className={styles.mainPhone}>
              {mainPhone.display}
            </a>
          ) : null}
          {mainPhone?.label ? <span className={styles.value}>{mainPhone.label}</span> : null}
          {otherPhones.map((phone) => (
            <a key={phone.tel} href={`tel:${phone.tel}`} className={styles.contact}>
              <span className={styles.contactValue}>{phone.display}</span>
              {phone.label ? <span className={styles.contactLabel}>{phone.label}</span> : null}
            </a>
          ))}
          {contacts?.emails?.map((email) => (
            <a key={email.email} href={`mailto:${email.email}`} className={styles.link}>
              {email.email}
            </a>
          ))}
          {contacts?.address ? <span className={styles.value}>{contacts.address}</span> : null}
          {contacts?.working_hours ? (
            <span className={styles.value}>{contacts.working_hours}</span>
          ) : null}
          {socials.length > 0 ? (
            <span className={styles.socials}>
              {socials.map((social) => (
                <a
                  key={social.network}
                  href={social.url}
                  className={styles.link}
                  target="_blank"
                  rel="noreferrer noopener"
                >
                  {SOCIAL_LABELS[social.network] ?? social.network}
                </a>
              ))}
            </span>
          ) : null}
          <QuickOrderButton className={styles.quick}>Быстрый заказ</QuickOrderButton>
        </address>
      </div>

      <div className={styles.bottom}>
        <div className={`container ${styles.bottomInner}`}>
          <span>
            © {year} {name}
          </span>
          {requisites?.company_name || requisites?.bin ? (
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
