'use client';

/**
 * Комментарии к заявке.
 *
 * По умолчанию комментарий внутренний. Ответ клиенту — только по явной
 * отметке и после подтверждения: backend называет флаг
 * `visible_to_customer` именно затем, чтобы видимость нельзя было открыть
 * случайно. Ответ виден в личном кабинете, если заявка отправлена оттуда.
 */

import { useState, type FormEvent } from 'react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { useConfirm } from '@/components/ui/Dialog';
import { Checkbox, Field, Textarea } from '@/components/ui/Field';
import { Icon } from '@/components/ui/Icon';
import { EmptyState } from '@/components/ui/States';
import { useToast } from '@/components/ui/Toast';
import { requestsApi } from '@/lib/api/endpoints';
import type { RequestComment } from '@/lib/api/types';
import { extractFieldErrors, isForbidden, isNotFound } from '@/lib/errors';
import { formatDateTime } from '@/lib/format';

import styles from './RequestDetail.module.css';

const MAX_COMMENT_BODY = 5000;

type Props = {
  requestId: number;
  comments: readonly RequestComment[];
  canWrite: boolean;
  onAdded: (comment: RequestComment) => void;
  onMissing: () => void;
};

export function RequestComments({ requestId, comments, canWrite, onAdded, onMissing }: Props) {
  const confirm = useConfirm();
  const toast = useToast();
  const [body, setBody] = useState('');
  const [visible, setVisible] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | undefined>();

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const text = body.trim();
    if (!text || saving) return;
    if (visible) {
      const approved = await confirm({
        title: 'Отправить ответ клиенту?',
        description:
          'Комментарий увидит клиент в личном кабинете, и ему придёт уведомление. Внутренние заметки так не отправляйте.',
        confirmLabel: 'Отправить клиенту',
        tone: 'primary',
      });
      if (!approved) return;
    }
    setSaving(true);
    setError(undefined);
    try {
      const created = await requestsApi.addComment(requestId, {
        body: text,
        visible_to_customer: visible,
      });
      onAdded(created);
      setBody('');
      setVisible(false);
      toast.success(
        created.is_internal ? 'Внутренний комментарий добавлен' : 'Ответ клиенту отправлен',
      );
    } catch (reason) {
      if (isNotFound(reason)) {
        toast.error('Заявка не найдена', reason);
        onMissing();
        return;
      }
      const fields = extractFieldErrors(reason);
      const fieldError = fields.body ?? fields._form;
      if (fieldError) setError(fieldError);
      toast.error(
        isForbidden(reason) ? 'Нет права добавлять комментарии' : 'Комментарий не сохранён',
        fieldError ? undefined : reason,
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={styles.comments}>
      {comments.length === 0 ? (
        <EmptyState icon="content" title="Комментариев пока нет" compact />
      ) : (
        <ol className={styles.commentList}>
          {comments.map((comment) => (
            <li
              key={comment.id}
              className={`${styles.comment} ${comment.is_internal ? '' : styles.commentPublic}`}
            >
              <div className={styles.commentHead}>
                <span className={styles.strong}>{comment.author?.full_name ?? 'Система'}</span>
                {comment.is_internal ? (
                  <Badge tone="neutral">
                    <Icon name="lock" size={12} /> Внутренний
                  </Badge>
                ) : (
                  <Badge tone="accent">
                    <Icon name="external" size={12} /> Виден клиенту
                  </Badge>
                )}
                <time className={styles.muted} dateTime={comment.created_at}>
                  {formatDateTime(comment.created_at)}
                </time>
              </div>
              <p className={styles.commentBody}>{comment.body}</p>
            </li>
          ))}
        </ol>
      )}

      {canWrite ? (
        <form className={styles.commentForm} onSubmit={onSubmit} noValidate>
          <Field label="Новый комментарий" error={error}>
            <Textarea
              rows={3}
              maxLength={MAX_COMMENT_BODY}
              placeholder={visible ? 'Ответ, который увидит клиент' : 'Заметка для коллег'}
              value={body}
              disabled={saving}
              onChange={(event) => setBody(event.target.value)}
            />
          </Field>
          <div className={styles.commentActions}>
            <Checkbox
              label="Показать клиенту в личном кабинете"
              checked={visible}
              disabled={saving}
              onChange={(event) => setVisible(event.target.checked)}
            />
            <Button
              type="submit"
              variant={visible ? 'primary' : 'secondary'}
              loading={saving}
              disabled={!body.trim()}
            >
              {visible ? 'Отправить клиенту' : 'Добавить комментарий'}
            </Button>
          </div>
        </form>
      ) : null}
    </div>
  );
}
