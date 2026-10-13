'use client';

/**
 * Изображения товара.
 *
 * Файл уходит из браузера прямо в объектное хранилище по presigned-ссылке
 * (lib/media.ts), backend лишь выдаёт ссылку, проверяет загруженный объект
 * и ставит обработку в очередь. Пока воркер строит варианты, галерея
 * периодически перечитывается и показывает статус.
 */

import { useEffect, useRef, useState, type DragEvent } from 'react';

import { useSession } from '@/components/session/SessionProvider';
import { Badge, EnumBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { useConfirm } from '@/components/ui/Dialog';
import { Icon } from '@/components/ui/Icon';
import { Card } from '@/components/ui/Layout';
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/States';
import { useToast } from '@/components/ui/Toast';
import { ApiError } from '@/lib/api/client';
import { productImagesApi } from '@/lib/api/endpoints';
import type { ProductImage, ProductImageList } from '@/lib/api/types';
import { Permission } from '@/lib/auth/permissions';
import { describeError, isForbidden } from '@/lib/errors';
import { formatBytes } from '@/lib/format';
import { useQuery } from '@/lib/hooks/useQuery';
import { MEDIA_STATUS } from '@/lib/labels';
import {
  documentType,
  failureText,
  hasPendingImages,
  IMAGE_ACCEPT,
  IMAGE_KIND_LABELS,
  moveItem,
  StorageUploadError,
  UPLOAD_STAGE_LABELS,
  uploadProductImage,
  type UploadStage,
} from '@/lib/media';

import type { SectionProps } from '../ProductEditorScreen';
import styles from '../ProductEditor.module.css';

/** Как часто перечитывать галерею, пока файлы обрабатываются. */
export const PROCESSING_POLL_MS = 2500;
/** Не опрашивать бесконечно: зависший файл покажется со статусом «Обработка». */
const MAX_POLLS = 48;

type UploadItem = {
  id: number;
  file: File;
  stage: UploadStage;
  percent: number;
  error: string | null;
};

function uploadErrorText(error: unknown): string {
  if (error instanceof StorageUploadError) return error.message;
  if (error instanceof ApiError && error.code === 'upload_rejected') {
    const reason = error.details?.failure_reason;
    return failureText(typeof reason === 'string' ? reason : null);
  }
  if (error instanceof ApiError && error.code === 'media_failed')
    return 'Файл отклонён при проверке';
  return describeError(error);
}

export function ImagesSection({ product, canWrite }: SectionProps) {
  const { can } = useSession();
  const confirm = useConfirm();
  const toast = useToast();
  const canUpload = canWrite && can(Permission.MEDIA_UPLOAD);
  const gallery = useQuery((signal) => productImagesApi.list(product.id, { signal }), [product.id]);
  const [uploads, setUploads] = useState<UploadItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [dragFrom, setDragFrom] = useState<number | null>(null);
  const [dropActive, setDropActive] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const uploadSeq = useRef(0);
  const polls = useRef(0);

  const images = gallery.data?.items ?? [];
  const pending = hasPendingImages(gallery.data);

  // Опрос, пока воркер обрабатывает файлы; прекращается сам.
  useEffect(() => {
    if (!pending) {
      polls.current = 0;
      return;
    }
    if (polls.current >= MAX_POLLS) return;
    const timer = window.setTimeout(() => {
      polls.current += 1;
      gallery.reload();
    }, PROCESSING_POLL_MS);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending, gallery.data]);

  const patchUpload = (id: number, patch: Partial<UploadItem>) =>
    setUploads((current) => current.map((item) => (item.id === id ? { ...item, ...patch } : item)));

  const runUpload = async (item: UploadItem) => {
    patchUpload(item.id, { stage: 'intent', percent: 0, error: null });
    try {
      const result = await uploadProductImage(product.id, item.file, {
        onStage: (stage, percent) => patchUpload(item.id, { stage, percent: percent ?? 0 }),
      });
      gallery.setData(result);
      setUploads((current) => current.filter((entry) => entry.id !== item.id));
    } catch (error) {
      patchUpload(item.id, { stage: 'error', error: uploadErrorText(error) });
    }
  };

  const addFiles = async (files: FileList | File[]) => {
    const items = Array.from(files).map((file) => {
      uploadSeq.current += 1;
      return { id: uploadSeq.current, file, stage: 'intent' as const, percent: 0, error: null };
    });
    if (items.length === 0) return;
    setUploads((current) => [...current, ...items]);
    // По очереди: порядок в галерее совпадает с порядком выбора файлов.
    for (const item of items) await runUpload(item);
  };

  const mutate = async (
    action: () => Promise<ProductImageList | void>,
    success: string,
    failure: string,
  ) => {
    setBusy(true);
    try {
      const result = await action();
      if (result) gallery.setData(result);
      else gallery.reload();
      toast.success(success);
    } catch (error) {
      toast.error(isForbidden(error) ? 'Нет права изменять изображения' : failure, error);
      // Порядок или набор изменили в другой вкладке — показываем актуальный.
      if (error instanceof ApiError && (error.status === 409 || error.status === 404))
        gallery.reload();
    } finally {
      setBusy(false);
    }
  };

  const reorder = (from: number, to: number) => {
    if (from === to) return;
    const next = moveItem(images, from, to);
    void mutate(
      () =>
        productImagesApi.reorder(
          product.id,
          next.map((image) => image.id),
        ),
      'Порядок изображений сохранён',
      'Порядок не сохранён',
    );
  };

  const detach = async (image: ProductImage) => {
    const approved = await confirm({
      title: 'Отвязать изображение?',
      description: image.is_main
        ? 'Это главное изображение: главным станет следующее по порядку. Файл останется в медиатеке.'
        : 'Изображение пропадёт из карточки товара. Файл останется в медиатеке.',
      confirmLabel: 'Отвязать',
    });
    if (!approved) return;
    await mutate(
      () => productImagesApi.detach(product.id, image.id),
      'Изображение отвязано',
      'Не удалось отвязать',
    );
  };

  const onDropFiles = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDropActive(false);
    if (!canUpload || !event.dataTransfer.types.includes('Files')) return;
    void addFiles(event.dataTransfer.files);
  };

  if (gallery.status === 'error' && !gallery.data) {
    return (
      <Card title="Изображения">
        <ErrorState error={gallery.error} onRetry={gallery.reload} compact />
      </Card>
    );
  }

  return (
    <Card
      title="Изображения"
      description="Первое по порядку и главное изображение показываются в каталоге. На сайт попадают только обработанные файлы."
    >
      {canUpload ? (
        <div
          className={`${styles.dropzone} ${dropActive ? styles.dropzoneActive : ''}`}
          onDragOver={(event) => {
            if (event.dataTransfer.types.includes('Files')) {
              event.preventDefault();
              setDropActive(true);
            }
          }}
          onDragLeave={() => setDropActive(false)}
          onDrop={onDropFiles}
        >
          <Icon name="image" size={22} />
          <p>
            Перетащите файлы сюда или{' '}
            <button
              type="button"
              className={styles.linkButton}
              onClick={() => inputRef.current?.click()}
            >
              выберите на компьютере
            </button>
          </p>
          <p className={styles.muted}>JPEG, PNG или WebP. Размер и формат проверяет сервер.</p>
          <input
            ref={inputRef}
            type="file"
            accept={IMAGE_ACCEPT}
            multiple
            className="visually-hidden"
            aria-label="Загрузить изображения"
            onChange={(event) => {
              if (event.target.files) void addFiles(event.target.files);
              event.target.value = '';
            }}
          />
        </div>
      ) : null}

      {uploads.length > 0 ? (
        <ul className={styles.uploadList} aria-label="Загрузки">
          {uploads.map((item) => (
            <li
              key={item.id}
              className={`${styles.uploadItem} ${item.error ? styles.uploadFailed : ''}`}
            >
              <div className={styles.uploadInfo}>
                <span className={styles.strong}>{item.file.name}</span>
                <span className={styles.muted}>{formatBytes(item.file.size)}</span>
              </div>
              <div className={styles.uploadStatus} role="status">
                {item.error ? (
                  <span className={styles.errorText}>{item.error}</span>
                ) : (
                  <span>
                    {UPLOAD_STAGE_LABELS[item.stage]}
                    {item.stage === 'uploading' ? ` ${item.percent}%` : '…'}
                  </span>
                )}
                {item.stage === 'uploading' && !item.error ? (
                  <progress max={100} value={item.percent} className={styles.progress} />
                ) : null}
              </div>
              {item.error ? (
                <div className={styles.uploadActions}>
                  <Button size="sm" icon="refresh" onClick={() => void runUpload(item)}>
                    Повторить
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      setUploads((current) => current.filter((entry) => entry.id !== item.id))
                    }
                  >
                    Убрать
                  </Button>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}

      {!gallery.data ? (
        <div className={styles.galleryGrid} aria-busy="true">
          <Skeleton height={180} />
          <Skeleton height={180} />
        </div>
      ) : images.length === 0 ? (
        <EmptyState
          icon="image"
          title="Изображений нет"
          description={canUpload ? 'Загрузите фото — первое станет главным.' : undefined}
          compact
        />
      ) : (
        <ol className={styles.galleryGrid} aria-label="Галерея товара">
          {images.map((image, index) => (
            <li
              key={image.id}
              className={`${styles.imageCard} ${image.is_main ? styles.imageMain : ''} ${dragFrom === index ? styles.imageDragging : ''}`}
              draggable={canWrite && !busy}
              onDragStart={(event) => {
                event.dataTransfer.effectAllowed = 'move';
                event.dataTransfer.setData('text/plain', String(index));
                setDragFrom(index);
              }}
              onDragOver={(event) => {
                if (dragFrom !== null) event.preventDefault();
              }}
              onDrop={(event) => {
                event.preventDefault();
                if (dragFrom !== null) reorder(dragFrom, index);
                setDragFrom(null);
              }}
              onDragEnd={() => setDragFrom(null)}
            >
              <div className={styles.imagePreview}>
                {documentType(image.content_type) ? (
                  // Схема в PDF/DWG/DXF: превью нет — тип файла и ссылка.
                  <div className={styles.imagePlaceholder}>
                    <span className={styles.documentType}>{documentType(image.content_type)}</span>
                    {image.status === 'READY' && image.url ? (
                      <a href={image.url} target="_blank" rel="noopener noreferrer">
                        Открыть файл
                      </a>
                    ) : (
                      <span>
                        {image.status === 'FAILED' ? 'Файл не прошёл обработку' : 'Обрабатывается…'}
                      </span>
                    )}
                  </div>
                ) : image.status === 'READY' && (image.variants?.thumb || image.url) ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={image.variants?.large ?? image.url ?? image.variants?.thumb}
                    alt={image.alt?.ru ?? ''}
                    loading="lazy"
                  />
                ) : (
                  <div className={styles.imagePlaceholder}>
                    <Icon name={image.status === 'FAILED' ? 'alert' : 'image'} size={24} />
                    <span>
                      {image.status === 'FAILED' ? 'Файл не прошёл обработку' : 'Обрабатывается…'}
                    </span>
                  </div>
                )}
                {image.is_main ? (
                  <span className={styles.mainBadge}>
                    <Icon name="check" size={12} /> Главное
                  </span>
                ) : null}
              </div>
              <div className={styles.imageMeta}>
                <span className={styles.imagePosition}>{index + 1}</span>
                <span className={styles.imageName} title={image.original_filename ?? undefined}>
                  {image.original_filename ?? `Изображение ${image.id}`}
                </span>
                <EnumBadge value={image.status} meta={MEDIA_STATUS} />
                {image.kind !== 'PHOTO' ? (
                  <Badge tone="accent">{IMAGE_KIND_LABELS[image.kind] ?? image.kind}</Badge>
                ) : null}
                {!image.is_publicly_visible && image.status === 'READY' ? (
                  <Badge tone="warning">Не на сайте</Badge>
                ) : null}
              </div>
              {canWrite ? (
                <div className={styles.imageActions}>
                  <Button
                    size="sm"
                    variant="ghost"
                    icon="chevronLeft"
                    aria-label={`Переместить изображение ${index + 1} левее`}
                    disabled={busy || index === 0}
                    onClick={() => reorder(index, index - 1)}
                  />
                  <Button
                    size="sm"
                    variant="ghost"
                    icon="chevronRight"
                    aria-label={`Переместить изображение ${index + 1} правее`}
                    disabled={busy || index === images.length - 1}
                    onClick={() => reorder(index, index + 1)}
                  />
                  {!image.is_main && !documentType(image.content_type) ? (
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={busy || image.status === 'FAILED'}
                      onClick={() =>
                        void mutate(
                          () => productImagesApi.setMain(product.id, image.id),
                          'Главное изображение изменено',
                          'Не удалось сделать главным',
                        )
                      }
                    >
                      Сделать главным
                    </Button>
                  ) : null}
                  <Button
                    size="sm"
                    variant="dangerGhost"
                    icon="trash"
                    aria-label={`Отвязать изображение ${index + 1}`}
                    disabled={busy}
                    onClick={() => void detach(image)}
                  />
                </div>
              ) : null}
            </li>
          ))}
        </ol>
      )}
      {pending ? (
        <p className={styles.muted} role="status">
          Идёт обработка изображений — статус обновится автоматически.
        </p>
      ) : null}
    </Card>
  );
}
