/**
 * Кнопка «В корзину».
 *
 * Одна кнопка на весь сайт: и в карточке каталога, и на странице
 * товара. Текст зависит от цены — у позиции «по запросу» обещать
 * расчёт стоимости нельзя. Корзина здесь — состав будущей заявки:
 * оплаты на сайте нет.
 *
 * В узкой карточке каталога видна короткая подпись («В корзину»),
 * а доступное имя остаётся полным и начинается с видимого текста
 * по смыслу — средство чтения с экрана и голосовое управление
 * находят кнопку одинаково.
 */

'use client';

import { useEffect, useState } from 'react';

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
  /** Короткая видимая подпись для карточки каталога. */
  compact?: boolean;
  /** Открывать панель сразу после добавления (страница товара). */
  openDrawer?: boolean;
  className?: string;
};

export function AddToRequestButton({
  line,
  quantity,
  onRequestPrice = false,
  size = 'md',
  variant = 'primary',
  block = true,
  compact = false,
  openDrawer = false,
  className,
}: AddToRequestButtonProps) {
  const { add, has } = useRequest();
  const { open } = useRequestDrawer();
  const [justAdded, setJustAdded] = useState(false);

  // Другой цвет — другая позиция: «Добавлено ✓» относилось к прежней.
  useEffect(() => setJustAdded(false), [line.color]);

  const inRequest = has(line.sku, line.color);
  const fullLabel = onRequestPrice ? 'Запросить стоимость' : 'Добавить в корзину';
  const shortLabel = onRequestPrice ? 'Запросить' : 'В корзину';

  let visible: string;
  let accessible: string | undefined;
  if (justAdded) {
    visible = 'Добавлено ✓';
    accessible = compact ? 'Добавлено в корзину' : undefined;
  } else if (inRequest) {
    visible = compact ? 'Ещё' : 'Добавить ещё';
    accessible = compact ? 'Добавить ещё в корзину' : undefined;
  } else {
    visible = compact ? shortLabel : fullLabel;
    accessible = compact ? fullLabel : undefined;
  }

  return (
    <Button
      type="button"
      size={size}
      variant={inRequest && !justAdded ? 'outline' : variant}
      block={block}
      className={className}
      aria-label={accessible}
      onClick={() => {
        add({ ...line, quantity });
        setJustAdded(true);
        window.setTimeout(() => setJustAdded(false), 1600);
        if (openDrawer) open();
      }}
    >
      {visible}
    </Button>
  );
}
