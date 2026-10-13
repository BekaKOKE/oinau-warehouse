/**
 * Поведение модального окна: фокус внутри, Esc закрывает, фон не
 * прокручивается, после закрытия фокус возвращается туда, откуда окно
 * открыли. Без этого окно непроходимо с клавиатуры и «протекает» на
 * страницу под собой.
 *
 * Общий хук для панели корзины и окна быстрого заказа.
 */

'use client';

import { useEffect, useRef, type RefObject } from 'react';

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function useModalDialog(
  panelRef: RefObject<HTMLElement | null>,
  isOpen: boolean,
  onClose: () => void,
) {
  // Обработчик закрытия меняется на каждом рендере родителя; эффект
  // не должен из-за этого снимать и заново ставить ловушку фокуса.
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });

  useEffect(() => {
    if (!isOpen) return;

    const restoreFocusTo = document.activeElement as HTMLElement | null;
    const { overflow } = document.body.style;
    document.body.style.overflow = 'hidden';

    const panel = panelRef.current;
    const initial =
      panel?.querySelector<HTMLElement>('[data-autofocus]') ??
      panel?.querySelector<HTMLElement>(FOCUSABLE);
    initial?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault();
        close.current();
        return;
      }
      if (event.key !== 'Tab' || !panel) return;

      const focusable = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!first || !last) return;

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = overflow;
      restoreFocusTo?.focus();
    };
  }, [isOpen, panelRef]);
}
