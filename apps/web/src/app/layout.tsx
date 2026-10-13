import type { Metadata, Viewport } from 'next';
import { Golos_Text } from 'next/font/google';

import { MobileTabBar } from '@/components/layout/MobileTabBar';
import { Providers } from '@/components/layout/Providers';
import { SiteFooter } from '@/components/layout/SiteFooter';
import { SiteHeader } from '@/components/layout/SiteHeader';
import { WhatsAppButton } from '@/components/layout/WhatsAppButton';
import { RevealOnScroll } from '@/components/ui/RevealOnScroll';
import { fetchCategories } from '@/lib/api/catalog';
import { fetchContacts, fetchSiteSettings } from '@/lib/api/content';
import { SITE_NAME, SITE_TAGLINE, SITE_URL } from '@/lib/config';

import './globals.css';

// Шрифты обслуживает next/font: файлы отдаются со своего домена,
// сторонних запросов из браузера нет, а CLS не возникает — размеры
// подставляются на этапе сборки. Golos Text — вариативный, один файл
// на все начертания от обычного до сверхжирного.
const golos = Golos_Text({
  subsets: ['latin', 'cyrillic'],
  display: 'swap',
  variable: '--font-golos',
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

// `viewport-fit=cover` включает `env(safe-area-inset-*)` на iPhone:
// без него нижняя панель и плавающая кнопка не учитывают полосу «домой».
export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  themeColor: '#10162b',
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
    <html lang="ru" className={golos.variable}>
      <body>
        <a className="skipLink" href="#content">
          Перейти к содержимому
        </a>
        <Providers>
          <SiteHeader categories={categories} contacts={contacts} />
          <main id="content">{children}</main>
          <SiteFooter settings={settings} contacts={contacts} categories={categories} />
          <WhatsAppButton url={whatsapp} />
          <MobileTabBar />
          <RevealOnScroll />
        </Providers>
      </body>
    </html>
  );
}
