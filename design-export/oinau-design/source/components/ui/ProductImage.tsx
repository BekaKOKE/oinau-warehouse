/**
 * Изображение товара с фирменной заглушкой.
 *
 * Файлы витрина не хранит: ссылки приходят из медиатеки и ведут в CDN
 * (локально — MinIO). Отсутствие картинки — обычное состояние каталога,
 * а не сбой: карточка обязана выглядеть законченной и без фотографии.
 */

import Image from 'next/image';

import type { ProductImage as ProductImageType } from '@oinau/api-types';

import styles from './ProductImage.module.css';

export type ProductImageProps = {
  image?: ProductImageType | null;
  /** Показывается в заглушке — по нему видно, какой позиции нет фото. */
  label: string;
  alt?: string;
  sizes: string;
  priority?: boolean;
  fit?: 'cover' | 'contain';
  className?: string;
};

/**
 * Вариант нужного размера, если медиатека его собрала.
 * `url` — основной вариант (large) и всегда существует у READY-файла.
 */
function pickSource(image: ProductImageType, preferred: readonly string[]): string {
  for (const name of preferred) {
    const variant = image.variants?.[name];
    if (variant) return variant;
  }
  return image.url;
}

export function ProductImageView({
  image,
  label,
  alt,
  sizes,
  priority,
  fit = 'cover',
  className,
}: ProductImageProps) {
  const frameClass = [styles.frame, className ?? ''].filter(Boolean).join(' ');

  if (!image) {
    return (
      <div className={frameClass}>
        <div className={styles.placeholder}>
          <span className={styles.placeholderMark}>OINAU PRO</span>
          <span className={styles.placeholderLabel}>{label}</span>
        </div>
      </div>
    );
  }

  return (
    <div className={frameClass}>
      <Image
        src={pickSource(image, ['large', 'medium'])}
        alt={image.alt ?? alt ?? label}
        fill
        sizes={sizes}
        priority={priority}
        className={fit === 'contain' ? styles.contain : styles.image}
      />
    </div>
  );
}

export function thumbSource(image: ProductImageType): string {
  return pickSource(image, ['thumb', 'small', 'medium']);
}

export { styles as productImageStyles };
