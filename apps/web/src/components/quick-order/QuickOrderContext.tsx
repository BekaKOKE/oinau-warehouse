/**
 * Открытие окна «Быстрый заказ».
 *
 * Окно одно на весь сайт, открывают его отовсюду: кнопка в шапке,
 * hero, полоса «Знаете артикулы?», «1 клик» в карточке товара,
 * «Запросить КП» в разделе каталога. Каждый вызов может сразу выбрать
 * вкладку и подставить содержимое — список артикулов, товар, описание.
 */

'use client';

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';

import type { QuickRequestMode } from '@oinau/api-types';

/** Товар для «заказа в 1 клик» — снимок для показа, как в корзине. */
export type QuickOrderProduct = {
  sku: string;
  name: string;
  unit: string;
  /**
   * Минимальная партия. В списке каталога её нет (API отдаёт её только
   * в карточке товара): тогда количество можно не указывать — сервер
   * подставит минимальную партию сам.
   */
  minOrderQty?: number;
  /** Количество, уже выбранное на странице товара. */
  quantity?: number;
  priceLabel: string;
  imageUrl?: string;
  /** Цвет, выбранный на странице товара. */
  color?: string;
  colorName?: string;
};

export type QuickOrderOptions = {
  mode?: QuickRequestMode;
  skuList?: string;
  product?: QuickOrderProduct;
  comment?: string;
};

type QuickOrderState = {
  isOpen: boolean;
  /** Что передали при открытии; новое открытие — новые значения. */
  options: QuickOrderOptions;
  /** Меняется при каждом открытии: форма по нему сбрасывается. */
  session: number;
  open: (options?: QuickOrderOptions) => void;
  close: () => void;
};

const QuickOrderContext = createContext<QuickOrderState | null>(null);

export function QuickOrderProvider({ children }: { children: ReactNode }) {
  const [isOpen, setOpen] = useState(false);
  const [options, setOptions] = useState<QuickOrderOptions>({});
  const [session, setSession] = useState(0);

  const open = useCallback((next: QuickOrderOptions = {}) => {
    setOptions(next);
    setSession((value) => value + 1);
    setOpen(true);
  }, []);
  const close = useCallback(() => setOpen(false), []);

  const value = useMemo<QuickOrderState>(
    () => ({ isOpen, options, session, open, close }),
    [isOpen, options, session, open, close],
  );
  return <QuickOrderContext.Provider value={value}>{children}</QuickOrderContext.Provider>;
}

export function useQuickOrder(): QuickOrderState {
  const context = useContext(QuickOrderContext);
  if (!context) {
    throw new Error('useQuickOrder используется вне QuickOrderProvider');
  }
  return context;
}
