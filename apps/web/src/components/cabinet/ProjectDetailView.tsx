/**
 * Карточка проекта: описание, позиции и связанные заявки.
 *
 * Позицию добавляют по артикулу; подсказки — из избранного, чтобы
 * не переписывать артикулы вручную. Снятый с публикации товар остаётся
 * в проекте по снимку, но без ссылки на карточку.
 */

'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useId, useState } from 'react';

import type { CustomerFavorite, ProjectDetail } from '@oinau/api-types';

import { Button, ButtonLink } from '@/components/ui/Button';
import { TextField } from '@/components/ui/Field';
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/States';
import { ApiError } from '@/lib/api/client';
import {
  addProjectItem,
  deleteProject,
  fetchFavorites,
  fetchProject,
  MAX_PAGE_SIZE,
  removeProjectItem,
} from '@/lib/api/customer';
import {
  describeCabinetError,
  describeProjectStatus,
  describeRequestStatus,
  fieldErrorsFrom,
  formatDate,
  formatMoney,
} from '@/lib/cabinet/format';
import { formatQuantity } from '@/lib/format';
import { ConfirmDialog, FormAlert, StatusBadge } from './CabinetUi';
import { ProjectFormDialog } from './ProjectFormDialog';
import { useToast } from './Toaster';
import styles from './Cabinet.module.css';

const QUANTITY_PATTERN = /^\d{1,9}([.,]\d{1,3})?$/;

export function ProjectDetailView({ uuid }: { uuid: string }) {
  const router = useRouter();
  const toast = useToast();
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deletePending, setDeletePending] = useState(false);
  const [removingSku, setRemovingSku] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    fetchProject(uuid)
      .then((result) => {
        if (!cancelled) setProject(result);
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        if (caught instanceof ApiError && (caught.status === 404 || caught.status === 422)) {
          setNotFound(true);
        } else {
          setError(describeCabinetError(caught));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [uuid, attempt]);

  const back = (
    <Link href="/cabinet/projects" className={styles.backLink}>
      ← Все проекты
    </Link>
  );

  if (notFound) {
    return (
      <>
        {back}
        <EmptyState
          title="Проект не найден"
          text="Возможно, он был удалён."
          action={<ButtonLink href="/cabinet/projects">К списку проектов</ButtonLink>}
        />
      </>
    );
  }

  if (error) {
    return (
      <>
        {back}
        <ErrorState
          title="Не удалось загрузить проект"
          text={error}
          action={<Button onClick={() => setAttempt((value) => value + 1)}>Повторить</Button>}
        />
      </>
    );
  }

  if (!project) {
    return (
      <>
        {back}
        <div className={styles.rowsSkeleton} aria-busy="true" aria-label="Загрузка проекта">
          <Skeleton height="40px" width="50%" />
          <Skeleton height="180px" />
          <Skeleton height="120px" />
        </div>
      </>
    );
  }

  const status = describeProjectStatus(project.status);

  async function handleDelete() {
    if (!project) return;
    setDeletePending(true);
    try {
      await deleteProject(project.uuid);
      toast.success(`Проект «${project.name}» удалён`);
      router.replace('/cabinet/projects');
    } catch (caught) {
      toast.error(describeCabinetError(caught));
      setDeletePending(false);
    }
  }

  async function handleRemoveItem(sku: string) {
    if (!project) return;
    setRemovingSku(sku);
    try {
      await removeProjectItem(project.uuid, sku);
      setProject((current) =>
        current
          ? {
              ...current,
              items: current.items.filter((item) => item.sku !== sku),
              items_count: Math.max(current.items_count - 1, 0),
            }
          : current,
      );
      toast.success('Позиция убрана из проекта');
    } catch (caught) {
      toast.error(describeCabinetError(caught));
    } finally {
      setRemovingSku(null);
    }
  }

  return (
    <>
      {back}
      <header className={styles.pageHead}>
        <div className={styles.pageHeadText}>
          <p className={styles.eyebrow}>Проект</p>
          <h1 className={styles.pageTitle}>{project.name}</h1>
          <p className={styles.pageLead}>
            {project.region?.name ?? 'Регион не указан'} · создан {formatDate(project.created_at)}
          </p>
        </div>
        <div className={styles.pageActions}>
          <StatusBadge label={status.label} tone={status.tone} />
          <Button variant="outline" size="sm" block={false} onClick={() => setEditing(true)}>
            Изменить
          </Button>
          <Button
            variant="ghost"
            size="sm"
            block={false}
            className={styles.dangerText}
            onClick={() => setConfirmDelete(true)}
          >
            Удалить
          </Button>
        </div>
      </header>

      {project.description ? (
        <section className={styles.panel}>
          <h2 className={styles.panelTitle}>Описание</h2>
          <p className={styles.preLine}>{project.description}</p>
        </section>
      ) : null}

      <section className={styles.panel} aria-labelledby="project-items">
        <div className={styles.panelHead}>
          <h2 id="project-items" className={styles.panelTitle}>
            Позиции <span className={styles.panelCount}>{project.items.length}</span>
          </h2>
        </div>

        {project.items.length === 0 ? (
          <p className={styles.muted}>
            В проекте пока нет товаров. Добавьте позицию по артикулу ниже.
          </p>
        ) : (
          <ul className={styles.itemList}>
            {project.items.map((item) => (
              <li key={item.sku} className={styles.itemRow}>
                <div className={styles.itemMain}>
                  {item.slug ? (
                    <Link href={`/product/${item.slug}`} className={styles.itemNameLink}>
                      {item.name}
                    </Link>
                  ) : (
                    <span className={styles.itemName}>{item.name}</span>
                  )}
                  <span className={styles.itemMeta}>
                    <span className={styles.mono}>{item.sku}</span>
                    {item.is_available ? null : (
                      <span className={styles.unavailableBadge}>Недоступен</span>
                    )}
                  </span>
                  {item.note ? <span className={styles.itemNote}>{item.note}</span> : null}
                </div>
                <span className={`${styles.itemQty} ${styles.mono}`}>
                  {item.quantity ? formatQuantity(item.quantity) : '—'}
                </span>
                <Button
                  size="sm"
                  variant="outline"
                  block={false}
                  onClick={() => handleRemoveItem(item.sku)}
                  disabled={removingSku === item.sku}
                  aria-label={`Убрать из проекта: ${item.name}`}
                >
                  {removingSku === item.sku ? '…' : 'Убрать'}
                </Button>
              </li>
            ))}
          </ul>
        )}

        <AddItemForm
          uuid={project.uuid}
          existing={project.items.map((item) => item.sku)}
          onAdded={(updated) => {
            setProject(updated);
            toast.success('Позиция добавлена в проект');
          }}
        />
      </section>

      <section className={styles.panel} aria-labelledby="project-requests">
        <h2 id="project-requests" className={styles.panelTitle}>
          Заявки по проекту
        </h2>
        {project.requests.length === 0 ? (
          <p className={styles.muted}>Заявок, привязанных к проекту, пока нет.</p>
        ) : (
          <ul className={styles.compactList}>
            {project.requests.map((request) => {
              const requestStatus = describeRequestStatus(request.status);
              return (
                <li key={request.number}>
                  <Link
                    href={`/cabinet/requests/${encodeURIComponent(request.number)}`}
                    className={styles.compactRow}
                  >
                    <span className={styles.compactMain}>
                      <span className={styles.mono}>{request.number}</span>
                      <span className={styles.muted}>{formatDate(request.created_at)}</span>
                    </span>
                    <span className={styles.compactSide}>
                      <StatusBadge label={requestStatus.label} tone={requestStatus.tone} />
                      <span className={styles.amount}>
                        {formatMoney(request.total_estimate, request.currency)}
                      </span>
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {editing ? (
        <ProjectFormDialog
          project={project}
          onClose={() => setEditing(false)}
          onSaved={(updated) => {
            setProject(updated);
            setEditing(false);
            toast.success('Проект сохранён');
          }}
        />
      ) : null}

      {confirmDelete ? (
        <ConfirmDialog
          title="Удалить проект?"
          text={
            <>
              Проект «{project.name}» и его список позиций будут удалены. Отправленные заявки
              останутся в разделе «Заявки».
            </>
          }
          confirmLabel="Удалить проект"
          busy={deletePending}
          onCancel={() => setConfirmDelete(false)}
          onConfirm={handleDelete}
        />
      ) : null}
    </>
  );
}

function AddItemForm({
  uuid,
  existing,
  onAdded,
}: {
  uuid: string;
  existing: string[];
  onAdded: (project: ProjectDetail) => void;
}) {
  const listId = useId();
  const [favorites, setFavorites] = useState<CustomerFavorite[]>([]);
  const [sku, setSku] = useState('');
  const [quantity, setQuantity] = useState('');
  const [note, setNote] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchFavorites({ page: 1, pageSize: MAX_PAGE_SIZE })
      .then((result) => {
        if (!cancelled) setFavorites(result.items);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const suggestions = favorites.filter((favorite) => !existing.includes(favorite.sku));

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    const found: Record<string, string> = {};
    const cleanSku = sku.trim();
    const cleanQuantity = quantity.trim().replace(',', '.');
    if (!cleanSku) found.sku = 'Укажите артикул';
    else if (existing.includes(cleanSku)) found.sku = 'Этот товар уже есть в проекте';
    if (cleanQuantity && (!QUANTITY_PATTERN.test(cleanQuantity) || Number(cleanQuantity) <= 0)) {
      found.quantity = 'Количество — положительное число, до 3 знаков после запятой';
    }
    setErrors(found);
    if (Object.keys(found).length > 0) return;

    setPending(true);
    try {
      const updated = await addProjectItem(uuid, {
        sku: cleanSku,
        quantity: cleanQuantity || null,
        note: note.trim() || null,
      });
      setSku('');
      setQuantity('');
      setNote('');
      onAdded(updated);
    } catch (caught) {
      setErrors(fieldErrorsFrom(caught));
      if (caught instanceof ApiError && caught.code === 'product_unavailable') {
        setErrors({ sku: 'Товар с таким артикулом не найден или недоступен' });
      } else {
        setFormError(describeCabinetError(caught));
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <form className={styles.addItemForm} onSubmit={handleSubmit} noValidate>
      <h3 className={styles.formSubtitle}>Добавить позицию</h3>
      {formError ? <FormAlert>{formError}</FormAlert> : null}
      <div className={styles.addItemGrid}>
        <TextField
          label="Артикул"
          name="sku"
          required
          autoComplete="off"
          list={suggestions.length > 0 ? listId : undefined}
          placeholder="Например, RP-016"
          value={sku}
          onChange={(event) => setSku(event.target.value)}
          error={errors.sku}
          hint={suggestions.length > 0 ? 'Подсказки — из вашего избранного' : undefined}
          className={styles.mono}
        />
        <TextField
          label="Количество"
          name="quantity"
          inputMode="decimal"
          placeholder="Необязательно"
          value={quantity}
          onChange={(event) => setQuantity(event.target.value)}
          error={errors.quantity}
        />
        <TextField
          label="Заметка"
          name="note"
          maxLength={1000}
          placeholder="Необязательно"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          error={errors.note}
        />
        <div className={styles.addItemSubmit}>
          <Button type="submit" disabled={pending} aria-busy={pending}>
            {pending ? 'Добавляем…' : 'Добавить'}
          </Button>
        </div>
      </div>
      {suggestions.length > 0 ? (
        <datalist id={listId}>
          {suggestions.map((favorite) => (
            <option key={favorite.sku} value={favorite.sku}>
              {favorite.name}
            </option>
          ))}
        </datalist>
      ) : null}
    </form>
  );
}
