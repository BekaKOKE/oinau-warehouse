'use client';

/**
 * Смена статуса заявки.
 *
 * Список статусов — перечисление backend. Переходы backend не ограничивает,
 * поэтому доступен любой статус, кроме текущего; «Взять в работу» — лишь
 * короткий путь к IN_PROGRESS для новой заявки. Ответ PATCH — обновлённая
 * карточка, её и показываем без повторного запроса.
 */

import { useState, type FormEvent } from 'react';

import { EnumBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { useConfirm } from '@/components/ui/Dialog';
import { Field, Select, Textarea } from '@/components/ui/Field';
import { useToast } from '@/components/ui/Toast';
import { requestsApi } from '@/lib/api/endpoints';
import type { RequestDetail, RequestStatus } from '@/lib/api/types';
import { extractFieldErrors, isForbidden, isNotFound } from '@/lib/errors';
import { REQUEST_STATUS } from '@/lib/labels';
import { needsStatusConfirm, statusTargets } from '@/lib/requests';

import styles from './RequestDetail.module.css';

const MAX_STATUS_COMMENT = 2000;

type Props = {
  request: RequestDetail;
  canWrite: boolean;
  onUpdated: (request: RequestDetail) => void;
  onMissing: () => void;
};

export function RequestStatusPanel({ request, canWrite, onUpdated, onMissing }: Props) {
  const confirm = useConfirm();
  const toast = useToast();
  const [target, setTarget] = useState<RequestStatus | ''>('');
  const [comment, setComment] = useState('');
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const change = async (status: RequestStatus, note: string) => {
    if (saving) return;
    if (needsStatusConfirm(request.status, status)) {
      const approved = await confirm({
        title: `Перевести заявку в «${REQUEST_STATUS[status].label}»?`,
        description: `Сейчас: «${REQUEST_STATUS[request.status].label}». Переход попадёт в историю${
          note.trim() ? ' вместе с комментарием' : ''
        }; если заявка отправлена из личного кабинета, клиент увидит новый статус.`,
        confirmLabel: 'Сменить статус',
        tone: status === 'SPAM' || status === 'CANCELLED' ? 'danger' : 'primary',
      });
      if (!approved) return;
    }
    setSaving(true);
    setErrors({});
    try {
      const updated = await requestsApi.updateStatus(request.id, {
        status,
        comment: note.trim() || null,
      });
      onUpdated(updated);
      setTarget('');
      setComment('');
      toast.success(
        'Статус изменён',
        `Заявка ${updated.number}: ${REQUEST_STATUS[updated.status].label}`,
      );
    } catch (error) {
      if (isNotFound(error)) {
        toast.error('Заявка не найдена', error);
        onMissing();
        return;
      }
      const fields = extractFieldErrors(error);
      if (Object.keys(fields).length > 0) setErrors(fields);
      toast.error(
        isForbidden(error) ? 'Нет права менять статус' : 'Не удалось изменить статус',
        fields.comment || fields.status ? undefined : error,
      );
    } finally {
      setSaving(false);
    }
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (target) void change(target, comment);
  };

  return (
    <div className={styles.statusPanel}>
      <div className={styles.currentStatus}>
        <span className={styles.label}>Текущий статус</span>
        <EnumBadge value={request.status} meta={REQUEST_STATUS} />
      </div>

      {canWrite ? (
        <>
          {request.status === 'NEW' ? (
            <Button
              variant="primary"
              icon="check"
              className={styles.fullWidth}
              loading={saving && target === ''}
              disabled={saving}
              onClick={() => void change('IN_PROGRESS', '')}
            >
              Взять в работу
            </Button>
          ) : null}

          <form className={styles.statusForm} onSubmit={onSubmit} noValidate>
            <Field label="Новый статус" error={errors.status}>
              <Select
                options={statusTargets(request.status)}
                placeholder="Выберите статус"
                value={target}
                disabled={saving}
                onChange={(event) => setTarget(event.target.value as RequestStatus | '')}
              />
            </Field>
            <Field
              label="Комментарий к переходу"
              hint="Необязательно. Сохраняется в истории статусов."
              error={errors.comment}
            >
              <Textarea
                rows={2}
                maxLength={MAX_STATUS_COMMENT}
                value={comment}
                disabled={saving}
                onChange={(event) => setComment(event.target.value)}
              />
            </Field>
            <Button
              type="submit"
              variant="secondary"
              loading={saving && target !== ''}
              disabled={!target || saving}
              className={styles.fullWidth}
            >
              Сменить статус
            </Button>
          </form>
        </>
      ) : (
        <p className={styles.readOnly}>
          Только просмотр: у вашей роли нет права обрабатывать заявки.
        </p>
      )}
    </div>
  );
}
