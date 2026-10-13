/**
 * Статус наличия. Цвет — не единственный признак: рядом всегда текст,
 * иначе дальтоник не отличит «в наличии» от «нет в наличии».
 */

import type { PublicAvailability } from '@oinau/api-types';

import { describeAvailability } from '@/lib/format';
import styles from './Badge.module.css';

export function AvailabilityBadge({ value }: { value: PublicAvailability }) {
  const { label, tone } = describeAvailability(value);
  return (
    <span className={`${styles.badge} ${styles[tone]}`}>
      <span className={styles.dot} aria-hidden="true" />
      {label}
    </span>
  );
}

export { styles as badgeStyles };
