/**
 * Открытие панели заявки.
 *
 * Вынесено из `RequestProvider`, потому что состав заявки и
 * видимость панели живут по разным законам: состав переживает
 * перезагрузку, а открытая панель — нет.
 */

'use client';

import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';

type DrawerState = {
  isOpen: boolean;
  open: () => void;
  close: () => void;
};

const DrawerContext = createContext<DrawerState | null>(null);

export function RequestDrawerProvider({ children }: { children: ReactNode }) {
  const [isOpen, setOpen] = useState(false);
  const value = useMemo<DrawerState>(
    () => ({ isOpen, open: () => setOpen(true), close: () => setOpen(false) }),
    [isOpen],
  );
  return <DrawerContext.Provider value={value}>{children}</DrawerContext.Provider>;
}

export function useRequestDrawer(): DrawerState {
  const context = useContext(DrawerContext);
  if (!context) {
    throw new Error('useRequestDrawer используется вне RequestDrawerProvider');
  }
  return context;
}
