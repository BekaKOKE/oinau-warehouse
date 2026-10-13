import type { Metadata } from 'next';
import { IBM_Plex_Mono, Manrope } from 'next/font/google';

import { Providers } from '@/components/layout/Providers';
import { SiteFooter } from '@/components/layout/SiteFooter';
import { SiteHeader } from '@/components/layout/SiteHeader';
import { WhatsAppButton } from '@/components/layout/WhatsAppButton';
import { fetchCategories } from '@/lib/api/catalog';
import { fetchContacts, fetchSiteSettings } from '@/lib/api/content';
import { SITE_NAME, SITE_TAGLINE, SITE_URL } from '@/lib/config';

import './globals.css';

// Шрифты обслуживает next/font: файлы отдаются со своего домена,
// сторонних запросов из браузера нет, а CLS не возникает — размеры
// подставляются на этапе сборки.
const manrope = Manrope({
  subsets: ['latin', 'cyrillic'],
  weight: ['400', '500', '600', '700', '800'],
  display: 'swap',
  variable: '--font-manrope',
});

const plexMono = IBM_Plex_Mono({
  subsets: ['latin', 'cyrillic'],
  weight: ['400', '500', '600'],
  display: 'swap',
  variable: '--font-plex-mono',
});

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: `${SITE_NAME} — ${SITE_TAGLINE}`,
    template: `%s — ${SITE_NAME}`,
  },
  description: SITE_TAGLINE,
  robots: { index: true, follow: true },
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // Три запроса на весь макет. Они выполняются параллельно и кешируются
  // на стороне Next.js, поэтому каждая страница не ходит за ними заново.
  const [categories, settings, contacts] = await Promise.all([
    fetchCategories().catch(() => []),
    fetchSiteSettings(),
    fetchContacts(),
  ]);

  const whatsapp = contacts?.whatsapp?.url ?? settings?.whatsapp?.url ?? null;

  return (
    <html lang="ru" className={`${manrope.variable} ${plexMono.variable}`}>
      <body>
        <a className="skipLink" href="#content">
          Перейти к содержимому
        </a>
        <Providers>
          <SiteHeader categories={categories} />
          <main id="content">{children}</main>
          <SiteFooter settings={settings} contacts={contacts} categories={categories} />
          <WhatsAppButton url={whatsapp} />
        </Providers>
      </body>
    </html>
  );
}
