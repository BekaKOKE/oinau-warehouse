/**
 * Образцы цветов товара в каталоге: кружки цветов без выбора.
 *
 * Выбирается цвет на странице товара — там видны цена и наличие
 * каждого цвета. Здесь только подсказка, что цвета есть и какие.
 */

import type { ProductColorOption } from '@oinau/api-types';

import styles from './ColorSwatches.module.css';

const MAX_SHOWN = 6;

export function ColorSwatches({
  colors,
  className,
}: {
  colors: readonly ProductColorOption[] | undefined;
  className?: string;
}) {
  if (!colors || colors.length === 0) return null;
  const shown = colors.slice(0, MAX_SHOWN);
  const hidden = colors.length - shown.length;
  return (
    <p
      className={`${styles.swatches} ${className ?? ''}`}
      aria-label={`Цвета: ${colors.map((color) => color.name).join(', ')}`}
    >
      {shown.map((color) => (
        <span
          key={color.code}
          className={`${styles.swatch} ${color.availability === 'OUT_OF_STOCK' ? styles.out : ''}`}
          style={{ background: color.hex }}
          title={color.name}
          aria-hidden="true"
        />
      ))}
      {hidden > 0 ? (
        <span className={styles.more} aria-hidden="true">
          +{hidden}
        </span>
      ) : null}
    </p>
  );
}
