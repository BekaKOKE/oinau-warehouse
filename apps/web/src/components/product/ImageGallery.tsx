/**
 * Галерея карточки товара.
 *
 * Миниатюры — кнопки в списке: переключение должно работать
 * с клавиатуры. У товара без изображений показывается та же
 * фирменная заглушка, что и в каталоге.
 */

'use client';

import { useState } from 'react';

import type { ProductImage } from '@oinau/api-types';

import { ProductImageView, thumbSource } from '@/components/ui/ProductImage';
import styles from './Product.module.css';

const KIND_LABELS: Record<string, string> = {
  PHOTO: 'Фото',
  SCHEME: 'Схема',
  DRAWING: 'Чертёж',
  CERTIFICATE: 'Сертификат',
};

export function ImageGallery({
  images,
  sku,
  name,
}: {
  images: ProductImage[];
  sku: string;
  name: string;
}) {
  const [active, setActive] = useState(0);
  const current = images[active] ?? images[0];

  if (images.length === 0) {
    return (
      <div className={styles.stage}>
        <ProductImageView
          image={null}
          label={sku}
          sizes="(max-width: 1040px) 420px, 360px"
          className={styles.stageImage}
        />
      </div>
    );
  }

  return (
    <div className={styles.gallery}>
      {images.length > 1 ? (
        <ul className={styles.thumbs}>
          {images.map((image, index) => (
            <li key={image.url}>
              <button
                type="button"
                className={`${styles.thumb} ${index === active ? styles.thumbActive : ''}`}
                onClick={() => setActive(index)}
                aria-pressed={index === active}
                aria-label={`${KIND_LABELS[image.kind] ?? 'Изображение'} ${index + 1} из ${images.length}`}
              >
                {/* Миниатюра из медиатеки: небольшой готовый вариант,
                    оптимизация Next.js здесь ничего не добавит. */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={thumbSource(image)} alt="" loading="lazy" />
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      <div className={styles.stage}>
        <ProductImageView
          image={current}
          label={sku}
          alt={name}
          sizes="(max-width: 1040px) 420px, 360px"
          priority
          fit="contain"
          className={styles.stageImage}
        />
      </div>
    </div>
  );
}
