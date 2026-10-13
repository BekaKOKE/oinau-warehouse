'use client';

/**
 * Изображение раздела CMS — ссылка на файл медиатеки (UUID).
 *
 * Файл либо загружается существующим потоком (upload intent → PUT в
 * хранилище → complete), либо выбирается из медиатеки. В разделе хранится
 * только UUID; превью строится по ссылкам вариантов из backend, ключ
 * объекта в хранилище интерфейс не видит. «Убрать» удаляет только ссылку:
 * файл остаётся в медиатеке.
 */

import { useEffect, useId, useRef, useState } from 'react';

import { useSession } from '@/components/session/SessionProvider';
import { EnumBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/States';
import { ApiError } from '@/lib/api/client';
import { mediaApi } from '@/lib/api/endpoints';
import type { MediaDetail, MediaRead } from '@/lib/api/types';
import { Permission } from '@/lib/auth/permissions';
import { describeError, isNotFound } from '@/lib/errors';
import { formatBytes } from '@/lib/format';
import { useQuery } from '@/lib/hooks/useQuery';
import { MEDIA_STATUS } from '@/lib/labels';
import {
  failureText,
  IMAGE_ACCEPT,
  StorageUploadError,
  UPLOAD_STAGE_LABELS,
  uploadMediaFile,
  type UploadStage,
} from '@/lib/media';

import { useContentForm, useFieldError } from './FormContext';
import { MediaLibraryDialog } from './MediaLibraryDialog';
import styles from './Content.module.css';

/** Опрос файла, пока воркер строит варианты. */
export const MEDIA_POLL_MS = 2500;
const MAX_POLLS = 48;

function uploadErrorText(error: unknown): string {
  if (error instanceof StorageUploadError) return error.message;
  if (error instanceof ApiError && error.code === 'upload_rejected') {
    const reason = error.details?.failure_reason;
    return failureText(typeof reason === 'string' ? reason : null);
  }
  return describeError(error);
}

function previewUrl(media: Pick<MediaRead, 'url' | 'variants'>): string | null {
  return media.variants?.thumb ?? media.url ?? null;
}

type Upload = { stage: UploadStage; percent: number; error: string | null };

type MediaFieldProps = {
  label: string;
  path: string;
  value: string | null;
  onChange: (value: string | null) => void;
  hint?: string;
};

export function MediaField({ label, path, value, onChange, hint }: MediaFieldProps) {
  const { can } = useSession();
  const { disabled, clearErrors } = useContentForm();
  const error = useFieldError(path);
  const labelId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [upload, setUpload] = useState<Upload | null>(null);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const polls = useRef(0);

  const canUpload = can(Permission.CATALOG_WRITE, Permission.MEDIA_UPLOAD);
  const canBrowse = can(Permission.CATALOG_READ);

  const detail = useQuery((signal) => mediaApi.get(value ?? '', { signal }), [value], {
    enabled: value !== null,
  });
  const media: MediaDetail | undefined =
    value && detail.data?.uuid === value ? detail.data : undefined;
  const processing = media?.status === 'PENDING' || media?.status === 'PROCESSING';

  useEffect(() => {
    polls.current = 0;
  }, [value]);

  useEffect(() => {
    if (!processing || polls.current >= MAX_POLLS) return;
    const timer = window.setTimeout(() => {
      polls.current += 1;
      detail.reload();
    }, MEDIA_POLL_MS);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [processing, detail.data]);

  const select = (uuid: string | null) => {
    onChange(uuid);
    clearErrors(path);
  };

  const onFile = async (file: File) => {
    setUpload({ stage: 'intent', percent: 0, error: null });
    try {
      const created = await uploadMediaFile(file, 'CONTENT', {
        onStage: (stage, percent) => setUpload({ stage, percent: percent ?? 0, error: null }),
      });
      detail.setData({ ...created, products: [], content_sections: [] });
      select(created.uuid);
      setUpload(null);
    } catch (uploadError) {
      setUpload({ stage: 'error', percent: 0, error: uploadErrorText(uploadError) });
    }
  };

  const busy = upload !== null && upload.stage !== 'error';
  const missing = value !== null && detail.status === 'error' && isNotFound(detail.error);

  let preview;
  if (value === null) {
    preview = (
      <div className={styles.mediaEmpty}>
        <Icon name="image" size={22} />
        <span>Изображение не выбрано</span>
      </div>
    );
  } else if (missing) {
    preview = (
      <div className={`${styles.mediaEmpty} ${styles.mediaBroken}`}>
        <Icon name="alert" size={20} />
        <span>Файл не найден в медиатеке</span>
      </div>
    );
  } else if (detail.status === 'error' && !media) {
    preview = (
      <div className={`${styles.mediaEmpty} ${styles.mediaBroken}`}>
        <Icon name="alert" size={20} />
        <span>{describeError(detail.error)}</span>
        <Button size="sm" variant="ghost" icon="refresh" onClick={detail.reload}>
          Повторить
        </Button>
      </div>
    );
  } else if (!media) {
    preview = <Skeleton width="100%" height="100%" className={styles.mediaSkeleton} />;
  } else if (media.status === 'READY' && previewUrl(media)) {
    preview = (
      // Превью — вариант из хранилища; next/image здесь не нужен.
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={previewUrl(media) ?? undefined}
        alt={`Превью: ${media.original_filename ?? label}`}
        className={styles.mediaImage}
      />
    );
  } else {
    preview = (
      <div className={styles.mediaEmpty}>
        <Icon name={media.status === 'FAILED' ? 'alert' : 'image'} size={20} />
        <span>
          {media.status === 'FAILED'
            ? failureText(media.failure_reason)
            : 'Файл обрабатывается — превью появится автоматически'}
        </span>
      </div>
    );
  }

  return (
    <div className={styles.mediaField} role="group" aria-labelledby={labelId}>
      <span id={labelId} className={styles.fieldLabel}>
        {label}
      </span>
      <div className={`${styles.media} ${error ? styles.mediaInvalid : ''}`}>
        <div className={styles.mediaPreview}>{preview}</div>
        <div className={styles.mediaInfo}>
          {media ? (
            <>
              <span className={styles.mediaName} title={media.original_filename ?? undefined}>
                {media.original_filename ?? 'Без имени'}
              </span>
              <span className={styles.mediaMeta}>
                <EnumBadge value={media.status} meta={MEDIA_STATUS} />
                {media.width && media.height ? (
                  <span className="num">
                    {media.width}×{media.height}
                  </span>
                ) : null}
                <span className="num">{formatBytes(media.size_bytes)}</span>
              </span>
            </>
          ) : null}
          {upload ? (
            <p
              className={upload.error ? styles.errorText : styles.muted}
              role={upload.error ? 'alert' : 'status'}
            >
              {upload.error ??
                `${UPLOAD_STAGE_LABELS[upload.stage]}${
                  upload.stage === 'uploading' ? ` ${upload.percent}%` : '…'
                }`}
            </p>
          ) : null}
          {error ? (
            <p className={styles.errorText} role="alert">
              {error}
            </p>
          ) : hint ? (
            <p className={styles.muted}>{hint}</p>
          ) : null}
          {disabled ? null : (
            <div className={styles.mediaButtons}>
              {canUpload ? (
                <Button
                  size="sm"
                  icon="import"
                  loading={busy}
                  onClick={() => inputRef.current?.click()}
                >
                  {value ? 'Заменить' : 'Загрузить'}
                </Button>
              ) : null}
              {canBrowse ? (
                <Button
                  size="sm"
                  variant="ghost"
                  icon="image"
                  disabled={busy}
                  onClick={() => setLibraryOpen(true)}
                >
                  Из медиатеки
                </Button>
              ) : null}
              {value ? (
                <Button
                  size="sm"
                  variant="dangerGhost"
                  icon="close"
                  disabled={busy}
                  onClick={() => select(null)}
                  title="Файл останется в медиатеке"
                >
                  Убрать
                </Button>
              ) : null}
            </div>
          )}
          <input
            ref={inputRef}
            type="file"
            accept={IMAGE_ACCEPT}
            className="visually-hidden"
            tabIndex={-1}
            aria-label={`Файл: ${label}`}
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = '';
              if (file) void onFile(file);
            }}
          />
        </div>
      </div>
      <MediaLibraryDialog
        open={libraryOpen}
        onClose={() => setLibraryOpen(false)}
        onSelect={(item) => {
          detail.setData({ ...item, products: [], content_sections: [] });
          select(item.uuid);
          setLibraryOpen(false);
        }}
      />
    </div>
  );
}
