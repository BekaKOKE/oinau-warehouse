/**
 * Избранные позиции.
 *
 * Два режима с одним интерфейсом:
 *  - гость — список живёт в браузере (снимок для показа без запросов к API);
 *  - вошедший клиент — список хранится в аккаунте (/api/v1/customer/favorites),
 *    сердечко в каталоге сразу пишет на сервер.
 *
 * При входе позиции, сохранённые гостем, переносятся в аккаунт: человек
 * не должен терять собранный до регистрации список.
 */

'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import { useCustomerSession } from '@/components/cabinet/CustomerSessionProvider';
import { useToast } from '@/components/cabinet/Toaster';
import { ApiError } from '@/lib/api/client';
import { addFavorite, fetchAllFavoriteSkus, removeFavorite } from '@/lib/api/customer';
import { describeCabinetError } from '@/lib/cabinet/format';
import type { FavoriteItem } from '@/lib/favorite-item';

const STORAGE_KEY = 'oinau.favorites.v1';

type FavoritesState = {
  items: FavoriteItem[];
  ready: boolean;
  count: number;
  /** Список хранится в аккаунте клиента, а не в браузере. */
  synced: boolean;
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
  const { status } = useCustomerSession();
  const toast = useToast();
  const authenticated = status === 'authenticated';

  const [items, setItems] = useState<FavoriteItem[]>([]);
  const [localReady, setLocalReady] = useState(false);
  const [serverSkus, setServerSkus] = useState<Set<string> | null>(null);
  const itemsRef = useRef(items);
  itemsRef.current = items;

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      const parsed: unknown = raw ? JSON.parse(raw) : [];
      setItems(Array.isArray(parsed) ? parsed.filter(isItem) : []);
    } catch {
      setItems([]);
    }
    setLocalReady(true);
  }, []);

  useEffect(() => {
    if (!localReady) return;
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
    } catch {
      // Приватный режим: избранное работает до закрытия вкладки.
    }
  }, [items, localReady]);

  // Вход: перенести гостевой список в аккаунт и загрузить артикулы.
  useEffect(() => {
    if (!authenticated || !localReady) {
      setServerSkus(null);
      return;
    }
    let cancelled = false;
    (async () => {
      const moved = new Set<string>();
      for (const item of itemsRef.current) {
        try {
          await addFavorite(item.sku);
          moved.add(item.sku);
        } catch (error) {
          // Снятый с продажи товар в аккаунт не попадёт — и хранить его
          // локально дальше незачем. Сбой сети оставляет позицию до
          // следующей попытки.
          if (error instanceof ApiError && error.status < 500 && error.status !== 401) {
            moved.add(item.sku);
          }
        }
      }
      if (moved.size > 0) {
        setItems((current) => current.filter((item) => !moved.has(item.sku)));
      }
      const skus = await fetchAllFavoriteSkus();
      if (!cancelled) setServerSkus(new Set(skus));
    })().catch(() => {
      if (!cancelled) setServerSkus(new Set());
    });
    return () => {
      cancelled = true;
    };
  }, [authenticated, localReady]);

  const serverToggle = useCallback(
    async (sku: string, shouldAdd: boolean) => {
      const apply = (add: boolean) =>
        setServerSkus((current) => {
          const next = new Set(current ?? []);
          if (add) next.add(sku);
          else next.delete(sku);
          return next;
        });
      apply(shouldAdd);
      try {
        if (shouldAdd) await addFavorite(sku);
        else await removeFavorite(sku);
      } catch (error) {
        // Удаление того, чего на сервере уже нет, — не ошибка.
        if (!shouldAdd && error instanceof ApiError && error.status === 404) return;
        apply(!shouldAdd);
        toast.error(describeCabinetError(error));
      }
    },
    [toast],
  );

  const toggle = useCallback<FavoritesState['toggle']>(
    (item) => {
      if (authenticated) {
        void serverToggle(item.sku, !(serverSkus?.has(item.sku) ?? false));
        return;
      }
      setItems((current) =>
        current.some((saved) => saved.sku === item.sku)
          ? current.filter((saved) => saved.sku !== item.sku)
          : [...current, item],
      );
    },
    [authenticated, serverSkus, serverToggle],
  );

  const remove = useCallback<FavoritesState['remove']>(
    (sku) => {
      if (authenticated) {
        void serverToggle(sku, false);
        return;
      }
      setItems((current) => current.filter((item) => item.sku !== sku));
    },
    [authenticated, serverToggle],
  );

  const value = useMemo<FavoritesState>(() => {
    if (authenticated) {
      return {
        items: [],
        ready: serverSkus !== null,
        count: serverSkus?.size ?? 0,
        synced: true,
        has: (sku) => serverSkus?.has(sku) ?? false,
        toggle,
        remove,
      };
    }
    return {
      items,
      ready: localReady && status !== 'loading',
      count: items.length,
      synced: false,
      has: (sku) => items.some((item) => item.sku === sku),
      toggle,
      remove,
    };
  }, [authenticated, serverSkus, items, localReady, status, toggle, remove]);

  return <FavoritesContext.Provider value={value}>{children}</FavoritesContext.Provider>;
}

export function useFavorites(): FavoritesState {
  const context = useContext(FavoritesContext);
  if (!context) {
    throw new Error('useFavorites используется вне FavoritesProvider');
  }
  return context;
}
