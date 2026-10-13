'use client';

/**
 * Загрузка, редактирование и сохранение одного раздела CMS.
 *
 * Один компонент на все разделы: различаются только форма (SectionSpec)
 * и поля. Раздел сохраняется целиком (PUT) — тело собирается из формы
 * поле за полем по схеме backend, лишнего в него попасть не может.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
  type FormEvent,
} from 'react';

import { useSession } from '@/components/session/SessionProvider';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { useConfirm } from '@/components/ui/Dialog';
import { Switch } from '@/components/ui/Field';
import { Icon } from '@/components/ui/Icon';
import { Card } from '@/components/ui/Layout';
import { ErrorState, Skeleton } from '@/components/ui/States';
import { useToast } from '@/components/ui/Toast';
import { contentApi } from '@/lib/api/endpoints';
import type { ContentSectionKey, ContentSectionRead } from '@/lib/api/types';
import { Permission } from '@/lib/auth/permissions';
import { pathWithin, saveFieldErrors } from '@/lib/content/errors';
import { hasExtraLocale, sameForm } from '@/lib/content/fields';
import { sectionMeta, type SectionSpec } from '@/lib/content/sections';
import { isForbidden, type FieldErrors } from '@/lib/errors';
import { formatDateTime } from '@/lib/format';
import { useQuery } from '@/lib/hooks/useQuery';

import { ContentFormProvider, type ContentFormContextValue } from './FormContext';
import styles from './Content.module.css';

export type FieldsProps<Form> = {
  form: Form;
  update: (updater: (form: Form) => Form) => void;
};

type SectionEditorProps<K extends ContentSectionKey, Form> = {
  sectionKey: K;
  spec: SectionSpec<K, Form>;
  Fields: ComponentType<FieldsProps<Form>>;
  onDirtyChange: (dirty: boolean) => void;
};

export function SectionEditor<K extends ContentSectionKey, Form>(
  props: SectionEditorProps<K, Form>,
) {
  const { sectionKey } = props;
  const query = useQuery((signal) => contentApi.get(sectionKey, { signal }), [sectionKey]);

  if (query.status === 'error' && !query.data) {
    return (
      <Card>
        <ErrorState error={query.error} onRetry={query.reload} />
      </Card>
    );
  }
  if (!query.data) return <EditorSkeleton />;
  return <LoadedEditor {...props} read={query.data} onSaved={query.setData} />;
}

function EditorSkeleton() {
  return (
    <div className={styles.editor} role="status" aria-live="polite">
      <span className="visually-hidden">Загружаем раздел…</span>
      {[0, 1, 2].map((index) => (
        <div key={index} className={styles.panel}>
          <div className={styles.skeletonPanel}>
            <Skeleton width="30%" height={16} />
            <Skeleton width="55%" height={12} />
            <Skeleton height={36} />
            <Skeleton height={72} />
          </div>
        </div>
      ))}
    </div>
  );
}

function LoadedEditor<K extends ContentSectionKey, Form>({
  sectionKey,
  spec,
  Fields,
  onDirtyChange,
  read,
  onSaved,
}: SectionEditorProps<K, Form> & {
  read: ContentSectionRead<K>;
  onSaved: (read: ContentSectionRead<K>) => void;
}) {
  const { can } = useSession();
  const toast = useToast();
  const confirm = useConfirm();
  const canWrite = can(Permission.CONTENT_WRITE);
  const meta = sectionMeta(sectionKey);

  const [initial, setInitial] = useState<Form>(() => spec.fromData(read.data));
  const [form, setForm] = useState<Form>(initial);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [saving, setSaving] = useState(false);
  const [showKk, setShowKk] = useState(() => hasExtraLocale(initial));
  const [focusRequest, setFocusRequest] = useState(0);
  const formRef = useRef<HTMLFormElement>(null);
  const registered = useRef(new Map<string, number>());

  const dirty = !sameForm(form, initial);

  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);

  // Первое поле с ошибкой — в фокус: панель с ним уже раскрыта.
  useEffect(() => {
    if (focusRequest === 0) return;
    const timer = window.setTimeout(() => {
      formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [focusRequest]);

  const register = useCallback((path: string) => {
    const counts = registered.current;
    counts.set(path, (counts.get(path) ?? 0) + 1);
    return () => {
      const count = (counts.get(path) ?? 1) - 1;
      if (count > 0) counts.set(path, count);
      else counts.delete(path);
    };
  }, []);

  const clearErrors = useCallback((prefix: string) => {
    setErrors((current) => {
      const keys = Object.keys(current).filter((key) => pathWithin(key, [prefix]));
      if (keys.length === 0 && !current._form) return current;
      const next = { ...current };
      for (const key of keys) delete next[key];
      delete next._form;
      return next;
    });
  }, []);

  const context = useMemo<ContentFormContextValue>(
    () => ({ errors, disabled: !canWrite || saving, showKk, clearErrors, register }),
    [errors, canWrite, saving, showKk, clearErrors, register],
  );

  const update = useCallback((updater: (form: Form) => Form) => setForm(updater), []);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canWrite || saving || !dirty) return;
    const local = spec.validate(form);
    setErrors(local);
    if (Object.keys(local).length > 0) {
      setFocusRequest((value) => value + 1);
      return;
    }
    setSaving(true);
    try {
      const saved = await contentApi.save(sectionKey, spec.toPayload(form));
      const next = spec.fromData(saved.data);
      setInitial(next);
      setForm(next);
      setErrors({});
      onSaved(saved);
      toast.success(`Раздел «${meta.label}» сохранён`, 'Сайт покажет изменения в течение 5 минут.');
    } catch (error) {
      const fieldErrors = saveFieldErrors(error, spec.media(form));
      setErrors(fieldErrors);
      if (Object.keys(fieldErrors).length > 0) setFocusRequest((value) => value + 1);
      toast.error(isForbidden(error) ? 'Нет права изменять контент' : 'Раздел не сохранён', error);
    } finally {
      setSaving(false);
    }
  };

  const reset = async () => {
    const approved = await confirm({
      title: 'Отменить изменения?',
      description:
        'Все несохранённые правки раздела будут сброшены к последней сохранённой версии.',
      confirmLabel: 'Сбросить',
      cancelLabel: 'Продолжить редактирование',
    });
    if (!approved) return;
    setForm(initial);
    setErrors({});
  };

  const errorCount = Object.keys(errors).length;
  // Ошибки, для которых на экране нет поля (например, от новой проверки backend).
  const orphan = Object.entries(errors).filter(([key]) => !registered.current.has(key));

  return (
    <ContentFormProvider value={context}>
      <form ref={formRef} className={styles.editor} onSubmit={submit} noValidate>
        <div className={styles.editorBar}>
          <div className={styles.editorStatus}>
            {read.is_configured ? (
              <Badge tone="success" dot>
                Заполнен
              </Badge>
            ) : (
              <Badge tone="warning" dot>
                Ещё не сохранялся
              </Badge>
            )}
            {read.updated_at ? (
              <span className={styles.muted}>Изменён {formatDateTime(read.updated_at)}</span>
            ) : (
              <span className={styles.muted}>Сайт показывает тексты по умолчанию</span>
            )}
          </div>
          <Switch
            label="Казахская версия (KK)"
            description="Необязательно: основной контент — RU"
            checked={showKk}
            onChange={(event) => setShowKk(event.target.checked)}
          />
        </div>

        {!canWrite ? (
          <p className={styles.readOnly}>
            <Icon name="lock" size={14} /> Только просмотр: у вашей роли нет права изменять контент.
          </p>
        ) : null}

        {errorCount > 0 ? (
          <div className={styles.formAlert} role="alert">
            <p className={styles.strong}>
              Раздел не сохранён: проверьте отмеченные поля ({errorCount}).
            </p>
            {orphan.length > 0 ? (
              <ul>
                {orphan.map(([key, message]) => (
                  <li key={key}>{key === '_form' ? message : `${key}: ${message}`}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}

        <Fields form={form} update={update} />

        {canWrite ? (
          <div className={styles.saveBar}>
            <span className={dirty ? styles.dirtyNote : styles.muted} aria-live="polite">
              {dirty ? 'Есть несохранённые изменения' : 'Изменений нет'}
            </span>
            <div className={styles.saveButtons}>
              <Button variant="ghost" disabled={!dirty || saving} onClick={() => void reset()}>
                Отменить
              </Button>
              <Button type="submit" variant="primary" loading={saving} disabled={!dirty}>
                Сохранить
              </Button>
            </div>
          </div>
        ) : null}
      </form>
    </ContentFormProvider>
  );
}
