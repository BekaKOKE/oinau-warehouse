/**
 * Выбор цвета товара: образцы с названием и наличием каждого цвета.
 *
 * Группа радиокнопок, а не набор ссылок: цвет меняет позицию заказа,
 * а не страницу. Точное количество цвета не показывается — только
 * статус, как и у товара целиком.
 */

'use client';

import type { ProductColorOption } from '@oinau/api-types';

import { describeAvailability } from '@/lib/format';
import styles from './Product.module.css';

export function ColorPicker({
  colors,
  value,
  onChange,
}: {
  colors: ProductColorOption[];
  value: string;
  onChange: (code: string) => void;
}) {
  const selected = colors.find((color) => color.code === value);
  const status = selected ? describeAvailability(selected.availability) : null;

  return (
    <fieldset className={styles.colors}>
      <legend className={styles.colorsLegend}>
        Цвет: <strong>{selected?.name ?? 'не выбран'}</strong>
        {status ? (
          <span className={`${styles.colorStatus} ${styles[status.tone]}`}> · {status.label}</span>
        ) : null}
      </legend>
      <div className={styles.colorOptions}>
        {colors.map((color) => {
          const availability = describeAvailability(color.availability);
          return (
            <label
              key={color.code}
              className={`${styles.colorOption} ${color.code === value ? styles.colorChecked : ''} ${
                color.availability === 'OUT_OF_STOCK' ? styles.colorOut : ''
              }`}
              title={`${color.name} — ${availability.label}`}
            >
              <input
                type="radio"
                name="product-color"
                value={color.code}
                checked={color.code === value}
                onChange={() => onChange(color.code)}
                className="visuallyHidden"
                aria-label={`${color.name}, ${availability.label.toLowerCase()}`}
              />
              <span className={styles.colorSwatch} style={{ background: color.hex }} />
              <span className={styles.colorName}>{color.name}</span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

/** Цвет по умолчанию: первый в наличии, иначе первый в списке. */
export function defaultColor(colors: ProductColorOption[]): string {
  return (colors.find((color) => color.availability === 'IN_STOCK') ?? colors[0])?.code ?? '';
}
