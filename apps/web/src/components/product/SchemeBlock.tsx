/**
 * «Схема / чертёж» — отдельный блок страницы товара, не часть галереи.
 *
 * Файл отдаётся публичной копией из CDN: PDF открывается во встроенном
 * просмотрщике браузера, DWG/DXF сразу скачиваются (так их отдаёт CDN),
 * у схемы-изображения есть превью. На сервере ничего не рендерится.
 */

import type { ProductDocument } from '@oinau/api-types';

import styles from './Product.module.css';

const KIND_LABELS: Record<string, string> = {
  SCHEME: 'Схема',
  DRAWING: 'Чертёж',
  CERTIFICATE: 'Сертификат',
};

const TYPE_LABELS: Record<string, string> = {
  'application/pdf': 'PDF',
  'image/vnd.dwg': 'DWG',
  'image/vnd.dxf': 'DXF',
  'image/webp': 'Изображение',
};

function formatSize(bytes: number | null | undefined): string | null {
  if (!bytes) return null;
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} КБ`;
  return `${(bytes / (1024 * 1024)).toFixed(1).replace('.', ',')} МБ`;
}

/** Открыть в браузере можно PDF и изображение; DWG/DXF — только скачать. */
export function canOpen(document: ProductDocument): boolean {
  // MIME чертежей (image/vnd.dwg, image/vnd.dxf) формально «image/*»,
  // но браузер их не покажет — только скачивание.
  return document.content_type === 'application/pdf' || document.content_type === 'image/webp';
}

export function SchemeBlock({
  documents,
  productName,
}: {
  documents: ProductDocument[];
  productName: string;
}) {
  if (documents.length === 0) return null;

  return (
    <section className={styles.block} aria-labelledby="scheme-title">
      <h2 className={styles.blockTitle} id="scheme-title">
        Схема изделия
      </h2>
      <ul className={styles.documents}>
        {documents.map((document) => {
          const type = TYPE_LABELS[document.content_type] ?? 'Файл';
          const size = formatSize(document.size_bytes);
          const title = document.filename ?? `${KIND_LABELS[document.kind] ?? 'Схема'} ${type}`;
          return (
            <li key={document.url} className={styles.document}>
              <div className={styles.documentPreview}>
                {document.preview_url ? (
                  // Превью из медиатеки — готовый вариант CDN.
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={document.preview_url}
                    alt={`${KIND_LABELS[document.kind] ?? 'Схема'}: ${productName}`}
                    loading="lazy"
                  />
                ) : (
                  <span className={styles.documentType} aria-hidden="true">
                    {type}
                  </span>
                )}
              </div>
              <div className={styles.documentBody}>
                <p className={styles.documentTitle}>{title}</p>
                <p className={styles.documentMeta}>
                  {[KIND_LABELS[document.kind] ?? 'Схема', type, size].filter(Boolean).join(' · ')}
                </p>
                <div className={styles.documentActions}>
                  {canOpen(document) ? (
                    <a
                      href={document.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={styles.documentLink}
                    >
                      Открыть схему
                    </a>
                  ) : null}
                  <a
                    href={document.url}
                    download={document.filename ?? true}
                    className={styles.documentLink}
                  >
                    Скачать
                  </a>
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
