/**
 * Нижняя панель на телефоне: главная, каталог, корзина и быстрый заказ.
 *
 * Четыре действия, до которых палец дотягивается одной рукой. На
 * широком экране панели нет — те же действия в шапке.
 */

'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { useQuickOrder } from '@/components/quick-order/QuickOrderContext';
import { useRequestDrawer } from '@/components/request/RequestDrawerContext';
import { useRequest } from '@/components/request/RequestProvider';
import { formatCount } from '@/lib/format';
import { isNavActive } from '@/lib/navigation';
import styles from './MobileTabBar.module.css';

export function MobileTabBar() {
  const pathname = usePathname();
  const { count, ready } = useRequest();
  const drawer = useRequestDrawer();
  const quickOrder = useQuickOrder();
  const cartCount = ready ? count : 0;

  return (
    <nav className={styles.bar} aria-label="Быстрые действия">
      <Link href="/" className={styles.item} aria-current={pathname === '/' ? 'page' : undefined}>
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <path d="M3 9.5 10 3.5l7 6V17H3z" stroke="currentColor" strokeWidth="1.7" />
        </svg>
        Главная
      </Link>
      <Link
        href="/catalog"
        className={styles.item}
        aria-current={isNavActive(pathname, '/catalog') ? 'page' : undefined}
      >
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <path
            d="M3 3h6v6H3zM11 3h6v6h-6zM3 11h6v6H3zM11 11h6v6h-6z"
            stroke="currentColor"
            strokeWidth="1.7"
          />
        </svg>
        Каталог
      </Link>
      <button
        type="button"
        className={styles.item}
        onClick={drawer.open}
        aria-label={cartCount > 0 ? `Корзина: ${cartCount}` : 'Корзина'}
      >
        <span className={styles.iconWrap}>
          <svg width="20" height="20" viewBox="0 0 18 18" fill="none" aria-hidden="true">
            <path
              d="M1.5 2.5h2.2l1.9 9h8.6l1.6-6.5H4.6"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinejoin="round"
            />
            <path d="M6.5 15.5h1.6M12.4 15.5H14" stroke="currentColor" strokeWidth="2" />
          </svg>
          {cartCount > 0 ? (
            <span className={styles.badge} aria-hidden="true">
              {formatCount(cartCount)}
            </span>
          ) : null}
        </span>
        Корзина
      </button>
      <button
        type="button"
        className={`${styles.item} ${styles.order}`}
        onClick={() => quickOrder.open()}
      >
        <span className={styles.orderMark} aria-hidden="true" />
        Заказ
      </button>
    </nav>
  );
}
