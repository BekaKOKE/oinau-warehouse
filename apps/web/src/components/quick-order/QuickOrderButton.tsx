/**
 * Кнопка, открывающая окно «Быстрый заказ».
 *
 * Клиентский островок для серверных секций (hero, подвал, раздел
 * каталога): вся страница остаётся серверной, в браузер уезжает только
 * эта кнопка.
 */

'use client';

import { Button, type ButtonSize, type ButtonVariant } from '@/components/ui/Button';
import { useQuickOrder, type QuickOrderOptions } from './QuickOrderContext';

export function QuickOrderButton({
  options,
  children,
  variant = 'primary',
  size = 'md',
  block = false,
  className,
}: {
  options?: QuickOrderOptions;
  children: React.ReactNode;
  variant?: ButtonVariant;
  size?: ButtonSize;
  block?: boolean;
  className?: string;
}) {
  const { open } = useQuickOrder();
  return (
    <Button
      type="button"
      variant={variant}
      size={size}
      block={block}
      className={className}
      onClick={() => open(options)}
    >
      {children}
    </Button>
  );
}
