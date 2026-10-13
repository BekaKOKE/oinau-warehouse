/**
 * Три обязательных состояния любого экрана: загрузка, пусто, ошибка.
 *
 * Белый экран — не состояние: посетитель не понимает, всё ли сломалось
 * или данных просто нет.
 */

import type { ReactNode } from 'react';

import { ButtonLink } from './Button';
import styles from './States.module.css';

export function EmptyState({
  title,
  text,
  action,
}: {
  title: string;
  text?: string;
  action?: ReactNode;
}) {
  return (
    <div className={styles.state}>
      <div className={styles.icon} aria-hidden="true">
        ∅
      </div>
      <p className={styles.title}>{title}</p>
      {text ? <p className={styles.text}>{text}</p> : null}
      {action ? <div className={styles.actions}>{action}</div> : null}
    </div>
  );
}

export function ErrorState({
  title = 'Не удалось загрузить данные',
  text,
  action,
}: {
  title?: string;
  text?: string;
  action?: ReactNode;
}) {
  return (
    <div className={styles.state} role="alert">
      <div className={`${styles.icon} ${styles.errorIcon}`} aria-hidden="true">
        !
      </div>
      <p className={styles.title}>{title}</p>
      {text ? <p className={styles.text}>{text}</p> : null}
      <div className={styles.actions}>
        {action ?? (
          <ButtonLink href="/catalog" variant="outline">
            Перейти в каталог
          </ButtonLink>
        )}
      </div>
    </div>
  );
}

export function Skeleton({
  width,
  height,
  className,
}: {
  width?: string;
  height?: string;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={[styles.skeleton, className ?? ''].filter(Boolean).join(' ')}
      style={{ display: 'block', width: width ?? '100%', height: height ?? '1em' }}
    />
  );
}

/** Заглушка карточки товара на время загрузки списка. */
export function ProductCardSkeleton() {
  return (
    <div className={styles.cardSkeleton} aria-hidden="true">
      <Skeleton className={styles.cardSkeletonImage} height="auto" />
      <div className={styles.cardSkeletonBody}>
        <Skeleton height="16px" />
        <Skeleton height="12px" width="60%" />
        <Skeleton height="22px" width="45%" />
        <Skeleton height="38px" />
      </div>
    </div>
  );
}

export { styles as stateStyles };
