import Link from 'next/link';
import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from 'react';

import { Icon, type IconName } from './Icon';
import { Spinner } from './Spinner';
import styles from './Button.module.css';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'dangerGhost';
export type ButtonSize = 'sm' | 'md';

type CommonProps = {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: IconName;
  children?: ReactNode;
};

function classes(variant: ButtonVariant, size: ButtonSize, iconOnly: boolean, extra?: string) {
  return [styles.button, styles[variant], styles[size], iconOnly ? styles.iconOnly : '', extra]
    .filter(Boolean)
    .join(' ');
}

type ButtonProps = CommonProps &
  ButtonHTMLAttributes<HTMLButtonElement> & {
    loading?: boolean;
  };

export function Button({
  variant = 'secondary',
  size = 'md',
  icon,
  loading = false,
  disabled,
  children,
  className,
  type = 'button',
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={classes(variant, size, !children, className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <Spinner size={14} /> : icon ? <Icon name={icon} size={16} /> : null}
      {children}
    </button>
  );
}

type ButtonLinkProps = CommonProps &
  Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> & { href: string };

export function ButtonLink({
  variant = 'secondary',
  size = 'md',
  icon,
  children,
  className,
  href,
  ...rest
}: ButtonLinkProps) {
  return (
    <Link href={href} className={classes(variant, size, !children, className)} {...rest}>
      {icon ? <Icon name={icon} size={16} /> : null}
      {children}
    </Link>
  );
}
