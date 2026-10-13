/**
 * Список проектов: создание, редактирование и удаление.
 *
 * Удаление — только после подтверждения: вместе с проектом пропадает
 * собранный список позиций, а заявки остаются, но теряют привязку.
 */

'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';

import type { ProjectListItem, ProjectPage } from '@oinau/api-types';

import { Button } from '@/components/ui/Button';
import { EmptyState, ErrorState } from '@/components/ui/States';
import { CABINET_PAGE_SIZE, deleteProject, fetchProjects } from '@/lib/api/customer';
import { describeCabinetError, describeProjectStatus, formatDate } from '@/lib/cabinet/format';
import { formatCount, plural } from '@/lib/format';
import { CabinetPagination, ConfirmDialog, PageHead, RowsSkeleton, StatusBadge } from './CabinetUi';
import { ProjectFormDialog } from './ProjectFormDialog';
import { useToast } from './Toaster';
import styles from './Cabinet.module.css';

export function ProjectsList({ page, openCreate = false }: { page: number; openCreate?: boolean }) {
  const router = useRouter();
  const toast = useToast();
  const [data, setData] = useState<ProjectPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [creating, setCreating] = useState(openCreate);
  const [editing, setEditing] = useState<ProjectListItem | null>(null);
  const [deleting, setDeleting] = useState<ProjectListItem | null>(null);
  const [deletePending, setDeletePending] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    fetchProjects({ page, pageSize: CABINET_PAGE_SIZE })
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((caught: unknown) => {
        if (!cancelled) setError(describeCabinetError(caught));
      });
    return () => {
      cancelled = true;
    };
  }, [page, attempt]);

  // Ссылка «Новый проект» (?create=1) может прийти, когда список уже открыт.
  useEffect(() => {
    if (openCreate) setCreating(true);
  }, [openCreate]);

  const reload = () => setAttempt((value) => value + 1);

  async function confirmDelete() {
    if (!deleting) return;
    setDeletePending(true);
    try {
      await deleteProject(deleting.uuid);
      toast.success(`Проект «${deleting.name}» удалён`);
      setDeleting(null);
      reload();
    } catch (caught) {
      toast.error(describeCabinetError(caught));
    } finally {
      setDeletePending(false);
    }
  }

  return (
    <>
      <PageHead
        title="Проекты"
        lead="Собирайте позиции под конкретный объект и отслеживайте связанные заявки."
        actions={<Button onClick={() => setCreating(true)}>Создать проект</Button>}
      />

      {error ? (
        <ErrorState
          title="Не удалось загрузить проекты"
          text={error}
          action={<Button onClick={reload}>Повторить</Button>}
        />
      ) : !data ? (
        <RowsSkeleton rows={3} height="132px" />
      ) : data.items.length === 0 ? (
        <EmptyState
          title="Проектов пока нет"
          text="Создайте проект для площадки или объекта и добавляйте в него товары из каталога."
          action={<Button onClick={() => setCreating(true)}>Создать первый проект</Button>}
        />
      ) : (
        <>
          <ul className={styles.projectGrid}>
            {data.items.map((project) => {
              const status = describeProjectStatus(project.status);
              return (
                <li key={project.uuid} className={styles.projectCard}>
                  <div className={styles.projectCardHead}>
                    <StatusBadge label={status.label} tone={status.tone} />
                    <span className={styles.muted}>обновлён {formatDate(project.updated_at)}</span>
                  </div>
                  <h2 className={styles.projectName}>
                    <Link href={`/cabinet/projects/${project.uuid}`} className={styles.rowLink}>
                      {project.name}
                    </Link>
                  </h2>
                  <p className={styles.muted}>{project.region?.name ?? 'Регион не указан'}</p>
                  <div className={styles.projectMeta}>
                    <span>
                      <strong>{formatCount(project.items_count)}</strong>{' '}
                      {plural(project.items_count, ['позиция', 'позиции', 'позиций'])}
                    </span>
                    <span>
                      <strong>{formatCount(project.requests_count)}</strong>{' '}
                      {plural(project.requests_count, ['заявка', 'заявки', 'заявок'])}
                    </span>
                  </div>
                  <div className={styles.projectActions}>
                    <Button
                      size="sm"
                      variant="secondary"
                      block={false}
                      onClick={() => router.push(`/cabinet/projects/${project.uuid}`)}
                    >
                      Открыть
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      block={false}
                      onClick={() => setEditing(project)}
                      aria-label={`Редактировать проект «${project.name}»`}
                    >
                      Изменить
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      block={false}
                      className={styles.dangerText}
                      onClick={() => setDeleting(project)}
                      aria-label={`Удалить проект «${project.name}»`}
                    >
                      Удалить
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
          <CabinetPagination
            basePath="/cabinet/projects"
            page={data.page}
            pages={data.pages}
            total={data.total}
            shown={data.items.length}
          />
        </>
      )}

      {creating ? (
        <ProjectFormDialog
          onClose={() => setCreating(false)}
          onSaved={(project) => {
            setCreating(false);
            toast.success('Проект создан');
            router.push(`/cabinet/projects/${project.uuid}`);
          }}
        />
      ) : null}

      {editing ? (
        <ProjectFormDialog
          project={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            toast.success('Проект сохранён');
            reload();
          }}
        />
      ) : null}

      {deleting ? (
        <ConfirmDialog
          title="Удалить проект?"
          text={
            <>
              Проект «{deleting.name}» и его список позиций будут удалены. Отправленные заявки
              останутся в разделе «Заявки».
            </>
          }
          confirmLabel="Удалить проект"
          busy={deletePending}
          onCancel={() => setDeleting(null)}
          onConfirm={confirmDelete}
        />
      ) : null}
    </>
  );
}
