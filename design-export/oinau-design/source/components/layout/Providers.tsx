/**
 * Клиентские хранилища витрины: состав заявки, избранное и панель.
 *
 * Один клиентский компонент на весь макет — страницы и их секции
 * остаются серверными и не попадают в браузерный бандл.
 */

'use client';

import type { ReactNode } from 'react';

import { FavoritesProvider } from '@/components/favorites/FavoritesProvider';
import { RequestDrawer } from '@/components/request/RequestDrawer';
import { RequestDrawerProvider } from '@/components/request/RequestDrawerContext';
import { RequestProvider } from '@/components/request/RequestProvider';

export function Providers({ children }: { children: ReactNode }) {
  return (
    <FavoritesProvider>
      <RequestProvider>
        <RequestDrawerProvider>
          {children}
          <RequestDrawer />
        </RequestDrawerProvider>
      </RequestProvider>
    </FavoritesProvider>
  );
}
