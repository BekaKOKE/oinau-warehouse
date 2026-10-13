/**
 * «1 клик» — заказ одной позиции без корзины.
 *
 * Открывает окно быстрого заказа на вкладке «По телефону» с уже
 * выбранным товаром: посетитель оставляет только телефон и имя.
 */

'use client';

import { Button, type ButtonSize } from '@/components/ui/Button';
import { useQuickOrder, type QuickOrderProduct } from './QuickOrderContext';

export function OneClickButton({
  product,
  size = 'sm',
  className,
  label = '1 клик',
}: {
  product: QuickOrderProduct;
  size?: ButtonSize;
  className?: string;
  label?: string;
}) {
  const { open } = useQuickOrder();
  return (
    <Button
      type="button"
      variant="outline"
      size={size}
      className={className}
      // Доступное имя начинается с видимой подписи — голосовое
      // управление находит кнопку по тому, что на ней написано.
      aria-label={`${label}: ${product.name}`}
      onClick={() => open({ mode: 'CALLBACK', product })}
    >
      {label}
    </Button>
  );
}
