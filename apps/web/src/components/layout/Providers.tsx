/**
 * Клиентские хранилища витрины: сессия клиента, уведомления, корзина,
 * избранное, панель корзины и окно быстрого заказа.
 *
 * Один клиентский компонент на весь макет — страницы и их секции
 * остаются серверными и не попадают в браузерный бандл.
 *
 * Сессия — самый внешний слой: от неё зависит, где хранится избранное,
 * что показывает шапка и куда уходит быстрый заказ.
 */

'use client';

import type { ReactNode } from 'react';

import { CustomerSessionProvider } from '@/components/cabinet/CustomerSessionProvider';
import { ToastProvider } from '@/components/cabinet/Toaster';
import { FavoritesProvider } from '@/components/favorites/FavoritesProvider';
import { QuickOrderProvider } from '@/components/quick-order/QuickOrderContext';
import { QuickOrderDialog } from '@/components/quick-order/QuickOrderDialog';
import { RequestDrawer } from '@/components/request/RequestDrawer';
import { RequestDrawerProvider } from '@/components/request/RequestDrawerContext';
import { RequestProvider } from '@/components/request/RequestProvider';

export function Providers({ children }: { children: ReactNode }) {
  return (
    <CustomerSessionProvider>
      <ToastProvider>
        <FavoritesProvider>
          <RequestProvider>
            <RequestDrawerProvider>
              <QuickOrderProvider>
                {children}
                <RequestDrawer />
                <QuickOrderDialog />
              </QuickOrderProvider>
            </RequestDrawerProvider>
          </RequestProvider>
        </FavoritesProvider>
      </ToastProvider>
    </CustomerSessionProvider>
  );
}
