'use client';

/**
 * Защита от потери несохранённых изменений при закрытии вкладки.
 *
 * Внутренние переходы (смена секции карточки) подтверждает сам экран:
 * у App Router нет события «уход со страницы», которое можно отменить.
 */

import { useEffect } from 'react';

export function useUnsavedGuard(dirty: boolean): void {
  useEffect(() => {
    if (!dirty) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      // Для старых браузеров: без returnValue диалог не показывается.
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [dirty]);
}
