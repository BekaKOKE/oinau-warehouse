import type { Metadata } from 'next';

import { FavoritesList } from '@/components/favorites/FavoritesList';
import { Breadcrumbs } from '@/components/ui/Breadcrumbs';
import { buildMetadata } from '@/lib/seo';
import styles from '@/components/content/Page.module.css';

export const metadata: Metadata = buildMetadata({
  title: 'Избранное',
  description: 'Сохранённые позиции каталога OINAU PRO.',
  path: '/favorites',
  // Список у каждого посетителя свой — индексировать нечего.
  noindex: true,
});

export default function FavoritesPage() {
  return (
    <div className={`container ${styles.page}`}>
      <Breadcrumbs items={[{ href: '/', label: 'Главная' }, { label: 'Избранное' }]} />

      <header className={styles.header}>
        <h1 className={styles.title}>Избранное</h1>
        <p className={styles.lead}>
          Список сохраняется в вашем браузере. После входа в личный кабинет он переносится в
          аккаунт.
        </p>
      </header>

      <section className={styles.section}>
        <FavoritesList />
      </section>
    </div>
  );
}
