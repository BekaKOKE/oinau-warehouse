/**
 * Состояния экрана: загрузка, пусто, ошибка, нет прав.
 *
 * У каждой ошибки есть действие «Повторить»: админка — рабочий
 * инструмент, и тупик без кнопки хуже любого текста ошибки.
 */

import type { CSSProperties, ReactNode } from 'react';

import { describeError, isForbidden } from '@/lib/errors';

import { Button } from './Button';
import { Icon, type IconName } from './Icon';
import styles from './States.module.css';

export function Skeleton({
  width = '100%',
  height = 14,
  className,
}: {
  width?: CSSProperties['width'];
  height?: CSSProperties['height'];
  className?: string;
}) {
  return (
    <span
      className={[styles.skeleton, className].filter(Boolean).join(' ')}
      style={{ width, height }}
      aria-hidden="true"
    />
  );
}

type StateProps = {
  icon?: IconName;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
};

function StateBox({
  icon = 'empty',
  title,
  description,
  action,
  compact,
  tone,
}: StateProps & { tone: string }) {
  return (
    <div className={`${styles.state} ${compact ? styles.compact : ''} ${styles[tone] ?? ''}`}>
      <span className={styles.icon}>
        <Icon name={icon} size={compact ? 18 : 22} />
      </span>
      <p className={styles.title}>{title}</p>
      {description ? <p className={styles.description}>{description}</p> : null}
      {action ? <div className={styles.action}>{action}</div> : null}
    </div>
  );
}

export function EmptyState(props: StateProps) {
  return <StateBox tone="empty" {...props} />;
}

export function ForbiddenState({ compact }: { compact?: boolean }) {
  return (
    <StateBox
      tone="forbidden"
      icon="lock"
      title="Нет доступа"
      description="У вашей роли нет прав на этот раздел. Если доступ нужен для работы, обратитесь к администратору."
      compact={compact}
    />
  );
}

export function ErrorState({
  error,
  onRetry,
  compact,
}: {
  error: unknown;
  onRetry?: () => void;
  compact?: boolean;
}) {
  if (isForbidden(error)) return <ForbiddenState compact={compact} />;
  return (
    <div role="alert">
      <StateBox
        tone="error"
        icon="alert"
        title="Не удалось загрузить данные"
        description={describeError(error)}
        compact={compact}
        action={
          onRetry ? (
            <Button size="sm" icon="refresh" onClick={onRetry}>
              Повторить
            </Button>
          ) : null
        }
      />
    </div>
  );
}

export function PageLoader({ label = 'Загрузка…' }: { label?: string }) {
  return (
    <div className={styles.pageLoader} role="status" aria-live="polite">
      <Skeleton width={220} height={24} />
      <Skeleton width="60%" height={14} />
      <div className={styles.loaderBlock}>
        <Skeleton height={120} />
      </div>
      <span className="visually-hidden">{label}</span>
    </div>
  );
}
