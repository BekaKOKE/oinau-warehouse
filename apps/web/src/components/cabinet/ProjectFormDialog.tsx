/**
 * Создание и редактирование проекта в модальном окне.
 *
 * При редактировании уходят только изменённые поля: пустое описание
 * отправляется как `null` и очищает его на сервере.
 */

'use client';

import { useEffect, useState } from 'react';

import type {
  ProjectCreate,
  ProjectDetail,
  ProjectListItem,
  ProjectStatus,
  ProjectUpdate,
  Region,
} from '@oinau/api-types';

import { createProject, updateProject } from '@/lib/api/customer';
import { fetchRegions } from '@/lib/api/requests';
import {
  PROJECT_STATUS,
  PROJECT_STATUSES,
  describeCabinetError,
  fieldErrorsFrom,
} from '@/lib/cabinet/format';
import { Button } from '@/components/ui/Button';
import { SelectField, TextAreaField, TextField } from '@/components/ui/Field';
import { FormAlert, Modal } from './CabinetUi';
import styles from './Cabinet.module.css';

type Values = { name: string; description: string; region_id: string; status: ProjectStatus };

export function ProjectFormDialog({
  project,
  onClose,
  onSaved,
}: {
  project?: ProjectListItem & { description?: string | null };
  onClose: () => void;
  onSaved: (project: ProjectDetail) => void;
}) {
  const editing = Boolean(project);
  const initial: Values = {
    name: project?.name ?? '',
    description: project?.description ?? '',
    region_id: project?.region ? String(project.region.id) : '',
    status: project?.status ?? 'PLANNING',
  };
  const [values, setValues] = useState<Values>(initial);
  const [regions, setRegions] = useState<Region[]>([]);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchRegions()
      .then((items) => {
        if (!cancelled) setRegions(items);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const set = (key: keyof Values) => (value: string) =>
    setValues((current) => ({ ...current, [key]: value }));

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    if (!values.name.trim()) {
      setErrors({ name: 'Назовите проект' });
      return;
    }
    setErrors({});
    setPending(true);
    try {
      let saved: ProjectDetail;
      if (project) {
        const changes: ProjectUpdate = {};
        if (values.name.trim() !== initial.name) changes.name = values.name.trim();
        if (values.description.trim() !== initial.description.trim()) {
          changes.description = values.description.trim() || null;
        }
        if (values.region_id !== initial.region_id) {
          changes.region_id = values.region_id ? Number(values.region_id) : null;
        }
        if (values.status !== initial.status) changes.status = values.status;
        saved = await updateProject(project.uuid, changes);
      } else {
        const payload: ProjectCreate = {
          name: values.name.trim(),
          description: values.description.trim() || null,
          region_id: values.region_id ? Number(values.region_id) : null,
          status: values.status,
        };
        saved = await createProject(payload);
      }
      onSaved(saved);
    } catch (error) {
      setErrors(fieldErrorsFrom(error));
      setFormError(describeCabinetError(error));
      setPending(false);
    }
  }

  const regionOptions =
    project?.region && !regions.some((region) => region.id === project.region?.id)
      ? [project.region, ...regions]
      : regions;

  return (
    <Modal
      title={editing ? 'Редактировать проект' : 'Новый проект'}
      onClose={onClose}
      busy={pending}
    >
      <form className={styles.form} onSubmit={handleSubmit} noValidate>
        {formError ? <FormAlert>{formError}</FormAlert> : null}
        <TextField
          label="Название"
          name="name"
          required
          maxLength={255}
          placeholder="Например, площадка во дворе ЖК «Алатау»"
          value={values.name}
          onChange={(event) => set('name')(event.target.value)}
          error={errors.name}
        />
        <TextAreaField
          label="Описание"
          name="description"
          maxLength={5000}
          rows={3}
          value={values.description}
          onChange={(event) => set('description')(event.target.value)}
          error={errors.description}
        />
        <div className={styles.formGrid}>
          <SelectField
            label="Регион"
            name="region_id"
            value={values.region_id}
            onChange={(event) => set('region_id')(event.target.value)}
            error={errors.region_id}
          >
            <option value="">Не указан</option>
            {regionOptions.map((region) => (
              <option key={region.id} value={region.id}>
                {region.name}
              </option>
            ))}
          </SelectField>
          <SelectField
            label="Статус"
            name="status"
            value={values.status}
            onChange={(event) => set('status')(event.target.value)}
            error={errors.status}
          >
            {PROJECT_STATUSES.map((status) => (
              <option key={status} value={status}>
                {PROJECT_STATUS[status].label}
              </option>
            ))}
          </SelectField>
        </div>
        <div className={styles.modalFooterInline}>
          <Button type="button" variant="outline" onClick={onClose} disabled={pending}>
            Отмена
          </Button>
          <Button type="submit" disabled={pending} aria-busy={pending}>
            {pending ? 'Сохраняем…' : editing ? 'Сохранить' : 'Создать проект'}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
