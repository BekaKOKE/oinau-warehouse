/**
 * Кнопка «в избранное».
 *
 * Иконка без текста, поэтому у неё обязательны `aria-label` и
 * `aria-pressed`: без них средство чтения с экрана объявит её как
 * безымянную кнопку и не скажет, добавлен товар или нет.
 */

'use client';

import type { FavoriteItem } from '@/lib/favorite-item';
import { useFavorites } from './FavoritesProvider';
import styles from './FavoriteButton.module.css';

export function FavoriteButton({ item, inline = false }: { item: FavoriteItem; inline?: boolean }) {
  const { has, toggle, ready } = useFavorites();
  const active = ready && has(item.sku);

  return (
    <button
      type="button"
      className={[styles.button, active ? styles.active : '', inline ? styles.inline : '']
        .filter(Boolean)
        .join(' ')}
      aria-pressed={active}
      aria-label={active ? `Убрать из избранного: ${item.name}` : `В избранное: ${item.name}`}
      onClick={() => toggle(item)}
    >
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
        <path
          d="M8 14S1.5 10.1 1.5 5.9A3.4 3.4 0 0 1 8 4.3a3.4 3.4 0 0 1 6.5 1.6C14.5 10.1 8 14 8 14Z"
          fill={active ? 'currentColor' : 'none'}
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinejoin="round"
        />
      </svg>
    </button>
  );
}
