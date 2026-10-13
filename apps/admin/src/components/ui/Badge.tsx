import type { ReactNode } from 'react';

import type { EnumMeta, Tone } from '@/lib/labels';

import styles from './Badge.module.css';

type BadgeProps = { tone?: Tone; children: ReactNode; dot?: boolean; title?: string };

export function Badge({ tone = 'neutral', children, dot = false, title }: BadgeProps) {
  return (
    <span className={`${styles.badge} ${styles[tone]}`} title={title}>
      {dot ? <span className={styles.dot} aria-hidden="true" /> : null}
      {children}
    </span>
  );
}

/** Бейдж значения перечисления: подпись и цвет берутся из `lib/labels.ts`. */
export function EnumBadge<K extends string>({
  value,
  meta,
}: {
  value: K;
  meta: Record<K, EnumMeta>;
}) {
  const item = meta[value];
  return (
    <Badge tone={item?.tone ?? 'neutral'} dot>
      {item?.label ?? value}
    </Badge>
  );
}
