/**
 * Кнопка «Добавить в заявку».
 *
 * Одна кнопка на весь сайт: и в карточке каталога, и на странице
 * товара. Текст зависит от цены — у позиции «по запросу» обещать
 * расчёт стоимости нельзя.
 */

'use client';

import { useState } from 'react';

import { Button, type ButtonSize, type ButtonVariant } from '@/components/ui/Button';
import { useRequestDrawer } from './RequestDrawerContext';
import type { NewRequestLine } from '@/lib/request-line';
import { useRequest } from './RequestProvider';

export type AddToRequestButtonProps = {
  line: NewRequestLine;
  quantity?: number;
  onRequestPrice?: boolean;
  size?: ButtonSize;
  variant?: ButtonVariant;
  block?: boolean;
  /** Открывать панель сразу после добавления (страница товара). */
  openDrawer?: boolean;
};

export function AddToRequestButton({
  line,
  quantity,
  onRequestPrice = false,
  size = 'md',
  variant = 'secondary',
  block = true,
  openDrawer = false,
}: AddToRequestButtonProps) {
  const { add, has } = useRequest();
  const { open } = useRequestDrawer();
  const [justAdded, setJustAdded] = useState(false);

  const inRequest = has(line.sku);
  const label = onRequestPrice ? 'Запросить стоимость' : 'Добавить в заявку';

  return (
    <Button
      type="button"
      size={size}
      variant={inRequest && !justAdded ? 'outline' : variant}
      block={block}
      onClick={() => {
        add({ ...line, quantity });
        setJustAdded(true);
        window.setTimeout(() => setJustAdded(false), 1600);
        if (openDrawer) open();
      }}
    >
      {justAdded ? 'Добавлено ✓' : inRequest ? 'Добавить ещё' : label}
    </Button>
  );
}
