/**
 * Избранные позиции.
 *
 * Личного кабинета на этом этапе нет, поэтому список живёт в браузере
 * посетителя. Хранится снимок для показа: открыть страницу избранного
 * без единого запроса к API дешевле, чем дёргать карточку каждого
 * товара по отдельности.
 */

'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import type { FavoriteItem } from '@/lib/favorite-item';

const STORAGE_KEY = 'oinau.favorites.v1';

type FavoritesState = {
  items: FavoriteItem[];
  ready: boolean;
  count: number;
  has: (sku: string) => boolean;
  toggle: (item: FavoriteItem) => void;
  remove: (sku: string) => void;
};

const FavoritesContext = createContext<FavoritesState | null>(null);

function isItem(value: unknown): value is FavoriteItem {
  if (typeof value !== 'object' || value === null) return false;
  const item = value as Record<string, unknown>;
  return (
    typeof item.sku === 'string' && typeof item.slug === 'string' && typeof item.name === 'string'
  );
}

export function FavoritesProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<FavoriteItem[]>([]);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      const parsed: unknown = raw ? JSON.parse(raw) : [];
      setItems(Array.isArray(parsed) ? parsed.filter(isItem) : []);
    } catch {
      setItems([]);
    }
    setReady(true);
  }, []);

  useEffect(() => {
    if (!ready) return;
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
    } catch {
      // Приватный режим: избранное работает до закрытия вкладки.
    }
  }, [items, ready]);

  const toggle = useCallback<FavoritesState['toggle']>((item) => {
    setItems((current) =>
      current.some((saved) => saved.sku === item.sku)
        ? current.filter((saved) => saved.sku !== item.sku)
        : [...current, item],
    );
  }, []);

  const remove = useCallback<FavoritesState['remove']>((sku) => {
    setItems((current) => current.filter((item) => item.sku !== sku));
  }, []);

  const value = useMemo<FavoritesState>(
    () => ({
      items,
      ready,
      count: items.length,
      has: (sku) => items.some((item) => item.sku === sku),
      toggle,
      remove,
    }),
    [items, ready, toggle, remove],
  );

  return <FavoritesContext.Provider value={value}>{children}</FavoritesContext.Provider>;
}

export function useFavorites(): FavoritesState {
  const context = useContext(FavoritesContext);
  if (!context) {
    throw new Error('useFavorites используется вне FavoritesProvider');
  }
  return context;
}
