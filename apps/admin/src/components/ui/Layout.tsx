/**
 * Каркас страницы: заголовок с действиями и карточки-секции.
 */

import Link from 'next/link';
import type { ReactNode } from 'react';

import { Icon } from './Icon';
import styles from './Layout.module.css';

export type Crumb = { label: string; href?: string };

type PageHeaderProps = {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  breadcrumbs?: readonly Crumb[];
  meta?: ReactNode;
};

export function PageHeader({ title, description, actions, breadcrumbs, meta }: PageHeaderProps) {
  return (
    <header className={styles.pageHeader}>
      {breadcrumbs && breadcrumbs.length > 0 ? (
        <nav aria-label="Навигация" className={styles.breadcrumbs}>
          {breadcrumbs.map((crumb, index) => (
            <span key={`${crumb.label}-${index}`} className={styles.crumb}>
              {index > 0 ? <Icon name="chevronRight" size={12} /> : null}
              {crumb.href ? (
                <Link href={crumb.href}>{crumb.label}</Link>
              ) : (
                <span>{crumb.label}</span>
              )}
            </span>
          ))}
        </nav>
      ) : null}
      <div className={styles.titleRow}>
        <div className={styles.titleBlock}>
          <h1 className={styles.title}>{title}</h1>
          {meta ? <div className={styles.meta}>{meta}</div> : null}
          {description ? <p className={styles.description}>{description}</p> : null}
        </div>
        {actions ? <div className={styles.actions}>{actions}</div> : null}
      </div>
    </header>
  );
}

type CardProps = {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  /** Без внутренних отступов — для таблиц во всю ширину карточки. */
  flush?: boolean;
  className?: string;
};

export function Card({
  title,
  description,
  actions,
  children,
  flush = false,
  className,
}: CardProps) {
  return (
    <section className={[styles.card, className].filter(Boolean).join(' ')}>
      {title || actions ? (
        <div className={styles.cardHeader}>
          <div>
            {title ? <h2 className={styles.cardTitle}>{title}</h2> : null}
            {description ? <p className={styles.cardDescription}>{description}</p> : null}
          </div>
          {actions ? <div className={styles.actions}>{actions}</div> : null}
        </div>
      ) : null}
      <div className={flush ? styles.cardBodyFlush : styles.cardBody}>{children}</div>
    </section>
  );
}

export function Toolbar({ children }: { children: ReactNode }) {
  return <div className={styles.toolbar}>{children}</div>;
}
