'use client';

import { useEffect, useMemo, useState, type FormEvent } from 'react';

import { Card } from '@/components/ui/Layout';
import { useToast } from '@/components/ui/Toast';
import { productsApi } from '@/lib/api/endpoints';
import {
  buildUpdatePayload,
  formFromProduct,
  isFormDirty,
  mainFormErrorsFromApi,
  validateMainForm,
  type MainForm,
  type MainFormErrors,
} from '@/lib/productForm';
import { isForbidden } from '@/lib/errors';

import { MainFields } from '../MainFields';
import type { SectionProps } from '../ProductEditorScreen';
import styles from '../ProductEditor.module.css';
import { SectionActions } from './SectionActions';

export function MainSection({ product, canWrite, onProductChange, onDirtyChange }: SectionProps) {
  const toast = useToast();
  const initial = useMemo(() => formFromProduct(product), [product]);
  const [form, setForm] = useState<MainForm>(initial);
  const [errors, setErrors] = useState<MainFormErrors>({});
  const [saving, setSaving] = useState(false);
  const dirty = isFormDirty(form, initial);

  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canWrite || saving) return;
    const localErrors = validateMainForm(form);
    setErrors(localErrors);
    if (Object.keys(localErrors).length > 0) return;
    const payload = buildUpdatePayload(form, product);
    if (Object.keys(payload).length === 0) return;
    setSaving(true);
    try {
      const updated = await productsApi.update(product.id, payload);
      onDirtyChange(false);
      onProductChange(updated);
      toast.success('Изменения сохранены');
    } catch (error) {
      setErrors(mainFormErrorsFromApi(error));
      toast.error(isForbidden(error) ? 'Нет права изменять товар' : 'Не сохранено', error);
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={onSubmit} noValidate>
      <Card title="Основная информация">
        {errors._form ? (
          <div className={styles.formAlert} role="alert">
            {errors._form}
          </div>
        ) : null}
        <MainFields
          form={form}
          errors={errors}
          disabled={!canWrite || saving}
          onChange={(patch) => setForm((current) => ({ ...current, ...patch }))}
        />
        {canWrite ? (
          <SectionActions
            dirty={dirty}
            saving={saving}
            onReset={() => {
              setForm(initial);
              setErrors({});
            }}
          />
        ) : null}
      </Card>
    </form>
  );
}
