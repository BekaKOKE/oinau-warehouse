import type { Metadata } from 'next';
import { Golos_Text } from 'next/font/google';

import { AppProviders } from '@/components/AppProviders';

import './globals.css';

// Тот же шрифт, что на сайте: одна система для витрины и админки.
// Вариативный Golos Text держит и плотные таблицы, и заголовки.
const golos = Golos_Text({
  subsets: ['latin', 'cyrillic'],
  variable: '--font-golos',
  display: 'swap',
});

export const metadata: Metadata = {
  title: { default: 'OINAU PRO — админка', template: '%s · OINAU PRO' },
  description: 'Панель управления каталогом и заявками OINAU PRO',
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru" className={golos.variable}>
      <body>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
