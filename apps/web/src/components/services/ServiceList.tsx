/**
 * Список услуг: строка на услугу, без карточек-плиток и декора.
 *
 * Как в каталоге: слева — что это и что именно делаем, справа —
 * условия и действие. Изображение необязательно и занимает узкую
 * колонку, а не половину экрана. Якорь `#slug` — чтобы на услугу
 * можно было сослаться из КП или письма.
 */

import Image from 'next/image';

import type { ServiceItem } from '@oinau/api-types';

import { QuickOrderButton } from '@/components/quick-order/QuickOrderButton';
import { ButtonLink } from '@/components/ui/Button';
import styles from './Services.module.css';

export function ServiceList({
  items,
  whatsappUrl,
}: {
  items: ServiceItem[];
  whatsappUrl?: string | null;
}) {
  return (
    <ol className={styles.list}>
      {items.map((service, index) => (
        <li key={service.slug} id={service.slug} className={styles.item}>
          <div className={styles.number} aria-hidden="true">
            {String(index + 1).padStart(2, '0')}
          </div>

          {service.image ? (
            <div className={styles.media}>
              <Image
                src={service.image.variants?.medium ?? service.image.url}
                alt=""
                width={service.image.width ?? 400}
                height={service.image.height ?? 300}
                sizes="(max-width: 860px) 100vw, 220px"
                className={styles.image}
              />
            </div>
          ) : null}

          <div className={styles.body}>
            <h2 className={styles.title}>{service.title}</h2>
            {service.summary ? <p className={styles.summary}>{service.summary}</p> : null}
            {service.details && service.details.length > 0 ? (
              <div className={styles.details}>
                <p className={styles.detailsTitle}>Что делаем</p>
                <ul className={styles.detailsList}>
                  {service.details.map((detail) => (
                    <li key={detail}>{detail}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>

          <div className={styles.aside}>
            {service.price_note ? <p className={styles.price}>{service.price_note}</p> : null}
            <QuickOrderButton
              block
              options={{ mode: 'QUOTE', comment: `Услуга: ${service.title}.` }}
            >
              {service.cta_label ?? 'Оставить заявку'}
            </QuickOrderButton>
            {whatsappUrl ? (
              <ButtonLink
                href={whatsappUrl}
                variant="outline"
                block
                target="_blank"
                rel="noopener noreferrer"
              >
                Получить консультацию
              </ButtonLink>
            ) : (
              <ButtonLink href="/contacts" variant="outline" block>
                Получить консультацию
              </ButtonLink>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}
