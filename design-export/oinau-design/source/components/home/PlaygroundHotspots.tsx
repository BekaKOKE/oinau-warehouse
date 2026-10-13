/**
 * Интерактивные метки на фотографии площадки.
 *
 * Каждая метка — настоящая ссылка в раздел каталога со счётчиком
 * позиций из API. Координаты и привязка к разделу приходят из
 * `lib/hotspots.ts`; компонент данные не придумывает.
 *
 * Разметка — список ссылок, а не набор `div` с обработчиками: метки
 * должны открываться в новой вкладке, обходиться клавишей Tab и
 * читаться как перечень разделов.
 */

import Link from 'next/link';

import { productCountLabel } from '@/lib/format';
import type { ResolvedHotspot } from '@/lib/hotspots';
import styles from './PlaygroundHotspots.module.css';

function cardStyle(hue: string): React.CSSProperties {
  return {
    background: `linear-gradient(135deg, ${hue}40, rgba(9, 14, 20, 0.94) 48%, rgba(9, 14, 20, 0.94))`,
    borderWidth: 1,
    borderStyle: 'solid',
    borderColor: `${hue}cc`,
    boxShadow: `0 0 0 1px rgba(0,0,0,.3), 0 0 20px ${hue}66, 0 10px 26px rgba(0,0,0,.5)`,
  };
}

/**
 * Видимая подпись — короткое название узла, поэтому ссылке нужно
 * доступное имя целиком: куда она ведёт и сколько там позиций.
 */
function linkLabel(spot: ResolvedHotspot): string {
  if (!spot.categoryName) return `${spot.name} — искать в каталоге`;
  const count = spot.productCount === null ? '' : `, ${productCountLabel(spot.productCount)}`;
  return `${spot.name} — раздел «${spot.categoryName}»${count}`;
}

export function PlaygroundHotspots({ hotspots }: { hotspots: ResolvedHotspot[] }) {
  return (
    <ul className={styles.layer} aria-label="Разделы каталога на фотографии площадки">
      {hotspots.map((spot) => (
        <li
          key={spot.id}
          className={styles.anchor}
          style={{ left: `${spot.x}%`, top: `${spot.y}%` }}
        >
          <Link
            href={spot.href}
            className={`${styles.card} ${spot.alignRight ? styles.alignRight : styles.alignLeft}`}
            style={cardStyle(spot.hue)}
            aria-label={linkLabel(spot)}
          >
            <span
              className={styles.dot}
              style={{ background: spot.hue, color: spot.hue, boxShadow: `0 0 12px ${spot.hue}` }}
              aria-hidden="true"
            >
              <span className={styles.pulse} style={{ background: `${spot.hue}80` }} />
            </span>
            <span className={styles.text}>
              <span className={styles.name}>{spot.name}</span>
              {spot.productCount !== null ? (
                <span className={styles.count}>{productCountLabel(spot.productCount)}</span>
              ) : null}
            </span>
            <span className={styles.arrow} style={{ background: spot.hue }} aria-hidden="true">
              →
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

/** Те же разделы прокручиваемым рядом — вариант для узкого экрана. */
export function PlaygroundHotspotsList({ hotspots }: { hotspots: ResolvedHotspot[] }) {
  return (
    <ul className={styles.mobileList}>
      {hotspots.map((spot) => (
        <li key={spot.id} className={styles.mobileItem}>
          <Link href={spot.href} className={styles.mobileLink} aria-label={linkLabel(spot)}>
            <span
              className={styles.mobileDot}
              style={{ background: spot.hue }}
              aria-hidden="true"
            />
            {spot.name}
            {spot.productCount !== null ? (
              <span className={styles.mobileCount}>{spot.productCount}</span>
            ) : null}
          </Link>
        </li>
      ))}
    </ul>
  );
}
