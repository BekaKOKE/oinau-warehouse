import Link from 'next/link';
import type { ReactNode } from 'react';

import { formatCount } from '@/lib/format';

import { Icon, type IconName } from './Icon';
import { Skeleton } from './States';
import styles from './StatCard.module.css';

type StatCardProps = {
  label: string;
  value: number | undefined;
  icon: IconName;
  tone?: 'blue' | 'cyan' | 'navy' | 'amber' | 'red' | 'green';
  hint?: ReactNode;
  href?: string;
  loading?: boolean;
  failed?: boolean;
};

export function StatCard({
  label,
  value,
  icon,
  tone = 'blue',
  hint,
  href,
  loading,
  failed,
}: StatCardProps) {
  const content = (
    <>
      <div className={styles.top}>
        <span className={styles.label}>{label}</span>
        <span className={`${styles.icon} ${styles[tone]}`}>
          <Icon name={icon} size={16} />
        </span>
      </div>
      <div className={styles.value}>
        {loading ? (
          <Skeleton width={64} height={28} />
        ) : failed || value === undefined ? (
          <span className={styles.failed} title="Не удалось загрузить">
            —
          </span>
        ) : (
          <span className="num">{formatCount(value)}</span>
        )}
      </div>
      {hint ? <div className={styles.hint}>{hint}</div> : null}
    </>
  );

  return href ? (
    <Link href={href} className={`${styles.card} ${styles.link}`}>
      {content}
    </Link>
  ) : (
    <div className={styles.card}>{content}</div>
  );
}
