/**
 * Список позиций заявки с изменением количества.
 *
 * Количество не опускается ниже минимальной партии товара: backend
 * отвергает такую заявку целиком, и узнать об этом после заполнения
 * контактов — худший момент.
 */

'use client';

import Link from 'next/link';

import { formatQuantity, unitLabel } from '@/lib/format';
import { lineKey, type RequestLine } from '@/lib/request-line';
import { useRequest } from './RequestProvider';
import styles from './RequestDrawer.module.css';

/** Название позиции для подписей кнопок: с цветом, если он выбран. */
function lineTitle(line: RequestLine): string {
  return line.colorName ? `${line.name}, ${line.colorName}` : line.name;
}

function QuantityControl({
  line,
  onChange,
}: {
  line: RequestLine;
  onChange: (quantity: number) => void;
}) {
  const minimum = line.minOrderQty || 1;
  const step = minimum < 1 ? minimum : 1;

  return (
    <div className={styles.qty}>
      <button
        type="button"
        className={styles.qtyButton}
        onClick={() => onChange(line.quantity - step)}
        disabled={line.quantity <= minimum}
        aria-label={`Уменьшить количество: ${lineTitle(line)}`}
      >
        −
      </button>
      <input
        className={styles.qtyInput}
        type="number"
        inputMode="decimal"
        min={minimum}
        step={step}
        value={line.quantity}
        onChange={(event) => {
          const next = Number(event.target.value);
          if (Number.isFinite(next)) onChange(next);
        }}
        aria-label={`Количество: ${lineTitle(line)}`}
      />
      <button
        type="button"
        className={styles.qtyButton}
        onClick={() => onChange(line.quantity + step)}
        aria-label={`Увеличить количество: ${lineTitle(line)}`}
      >
        +
      </button>
    </div>
  );
}

export function RequestLines() {
  const { lines, setQuantity, remove } = useRequest();

  return (
    <ul className={styles.lines}>
      {lines.map((line) => (
        <li key={lineKey(line)} className={styles.line}>
          <div className={styles.lineThumb}>
            {line.imageUrl ? (
              // Обычный <img>: ссылка приходит из медиатеки, и добавлять
              // домен CDN в next.config ради миниатюры в панели незачем.
              // eslint-disable-next-line @next/next/no-img-element
              <img src={line.imageUrl} alt="" loading="lazy" />
            ) : (
              <span>{line.sku}</span>
            )}
          </div>
          <div className={styles.lineBody}>
            <Link href={`/product/${line.slug}`} className={styles.lineName}>
              {line.name}
            </Link>
            {line.colorName ? (
              <p className={styles.lineColor}>
                <span
                  className={styles.lineSwatch}
                  style={{ background: line.colorHex }}
                  aria-hidden="true"
                />
                Цвет: {line.colorName}
              </p>
            ) : null}
            <div className={styles.lineMeta}>
              <span className={styles.lineSku}>{line.sku}</span>
              <span>{line.priceLabel}</span>
            </div>
            <div className={styles.lineControls}>
              <QuantityControl
                line={line}
                onChange={(value) => setQuantity(lineKey(line), value)}
              />
              <span className={styles.qtyUnit}>{unitLabel(line.unit)}</span>
              {line.minOrderQty > 1 ? (
                <span className={styles.qtyUnit}>
                  мин. {formatQuantity(String(line.minOrderQty))}
                </span>
              ) : null}
              <button
                type="button"
                className={styles.removeLine}
                onClick={() => remove(lineKey(line))}
                aria-label={`Убрать из корзины: ${lineTitle(line)}`}
              >
                Убрать
              </button>
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}
