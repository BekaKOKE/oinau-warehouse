/**
 * Кнопка и кнопка-ссылка с одним набором стилей.
 *
 * Ссылка остаётся ссылкой (`<a>`), а действие — кнопкой (`<button>`):
 * подменять одно другим нельзя, от этого зависит и клавиатура,
 * и средство чтения с экрана.
 */

import Link from 'next/link';
import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from 'react';

import styles from './Button.module.css';

export type ButtonVariant =
  'primary' | 'dark' | 'secondary' | 'outline' | 'ghost' | 'onDark' | 'light';

export type ButtonSize = 'sm' | 'md' | 'lg';

type CommonProps = {
  variant?: ButtonVariant;
  size?: ButtonSize;
  block?: boolean;
  className?: string;
  children: ReactNode;
};

function classes({ variant = 'primary', size = 'md', block, className }: CommonProps): string {
  return [styles.button, styles[variant], styles[size], block ? styles.block : '', className ?? '']
    .filter(Boolean)
    .join(' ');
}

export type ButtonProps = CommonProps & ButtonHTMLAttributes<HTMLButtonElement>;

export function Button({ variant, size, block, className, children, ...rest }: ButtonProps) {
  return (
    <button className={classes({ variant, size, block, className, children })} {...rest}>
      {children}
    </button>
  );
}

export type ButtonLinkProps = CommonProps &
  Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> & { href: string };

export function ButtonLink({
  variant,
  size,
  block,
  className,
  children,
  href,
  ...rest
}: ButtonLinkProps) {
  return (
    <Link href={href} className={classes({ variant, size, block, className, children })} {...rest}>
      {children}
    </Link>
  );
}
