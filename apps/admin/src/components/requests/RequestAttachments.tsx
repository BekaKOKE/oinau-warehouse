'use client';

/**
 * Файлы, приложенные клиентом к запросу КП.
 *
 * Прямой ссылкой файл не открыть: API требует заголовка Authorization.
 * Кнопка забирает файл запросом и отдаёт браузеру на сохранение — открыть
 * его «на месте» в админке нельзя и не нужно: файл прислал посетитель.
 */

import { useState } from 'react';

import { Button } from '@/components/ui/Button';
import { useToast } from '@/components/ui/Toast';
import { requestsApi } from '@/lib/api/endpoints';
import type { RequestAttachment } from '@/lib/api/types';
import { saveBlob } from '@/lib/download';
import { formatDateTime } from '@/lib/format';

import styles from './RequestDetail.module.css';

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`;
  return `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} МБ`;
}

export function RequestAttachments({
  requestId,
  attachments,
}: {
  requestId: number;
  attachments: RequestAttachment[];
}) {
  const toast = useToast();
  const [busy, setBusy] = useState<number | null>(null);

  const download = async (attachment: RequestAttachment) => {
    setBusy(attachment.id);
    try {
      const file = await requestsApi.downloadAttachment(requestId, attachment.id);
      saveBlob(file.blob, file.filename ?? attachment.filename);
    } catch (error) {
      toast.error('Не удалось скачать файл', error);
    } finally {
      setBusy(null);
    }
  };

  return (
    <ul className={styles.files}>
      {attachments.map((attachment) => (
        <li key={attachment.id} className={styles.file}>
          <span className={styles.fileMark} aria-hidden="true">
            {attachment.filename.split('.').pop()?.slice(0, 4).toUpperCase() ?? 'FILE'}
          </span>
          <span className={styles.fileBody}>
            <span className={styles.fileName}>{attachment.filename}</span>
            <span className={styles.muted}>
              {formatFileSize(attachment.size_bytes)} · {formatDateTime(attachment.created_at)}
            </span>
          </span>
          <Button
            variant="secondary"
            size="sm"
            icon="import"
            loading={busy === attachment.id}
            disabled={busy !== null}
            onClick={() => void download(attachment)}
            aria-label={`Скачать ${attachment.filename}`}
          >
            Скачать
          </Button>
        </li>
      ))}
    </ul>
  );
}
