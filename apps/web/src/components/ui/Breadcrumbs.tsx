/**
 * Хлебные крошки. Список ссылок в `<nav>`: цепочку разделов нужно
 * уметь обойти клавиатурой и прочитать как навигацию, а не как строку
 * с разделителями.
 */

import Link from 'next/link';

import styles from './Breadcrumbs.module.css';

export type Crumb = { href?: string; label: string };

export function Breadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <nav className={styles.nav} aria-label="Хлебные крошки">
      <ol className={styles.list}>
        {items.map((item, index) => {
          const last = index === items.length - 1;
          return (
            <li key={`${item.label}-${index}`}>
              {item.href && !last ? (
                <Link href={item.href} className={styles.link}>
                  {item.label}
                </Link>
              ) : (
                <span className={styles.current} aria-current={last ? 'page' : undefined}>
                  {item.label}
                </span>
              )}
              {last ? null : (
                <span className={styles.separator} aria-hidden="true">
                  {' / '}
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
