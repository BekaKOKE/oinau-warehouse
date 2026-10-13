'use client';

import { useEffect, useMemo, useState, type FormEvent } from 'react';

import { Card } from '@/components/ui/Layout';
import { useToast } from '@/components/ui/Toast';
import { ApiError } from '@/lib/api/client';
import { productsApi } from '@/lib/api/endpoints';
import {
  buildAttributeItems,
  sameItems,
  valuesFromProduct,
  type AttributeValues,
} from '@/lib/attributes';
import { describeError, isForbidden } from '@/lib/errors';

import { AttributeEditor, useAttributeDefs } from '../AttributeEditor';
import type { SectionProps } from '../ProductEditorScreen';
import styles from '../ProductEditor.module.css';
import { SectionActions } from './SectionActions';

export function AttributesSection({
  product,
  canWrite,
  onProductChange,
  onDirtyChange,
}: SectionProps) {
  const toast = useToast();
  const existing = product.attributes ?? [];
  const categoryIds = (product.categories ?? []).map((item) => item.category_id);
  const defs = useAttributeDefs(categoryIds, existing);
  const initial = useMemo(() => valuesFromProduct(product.attributes ?? []), [product]);
  const [values, setValues] = useState<AttributeValues>(initial);
  const [errors, setErrors] = useState<Record<number, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const list = defs.data ?? [];
  const current = buildAttributeItems(list, values);
  const saved = buildAttributeItems(list, initial);
  const dirty = !current.ok || (saved.ok && !sameItems(current.items, saved.items));

  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canWrite || saving) return;
    const built = buildAttributeItems(list, values);
    if (!built.ok) {
      setErrors(built.errors);
      return;
    }
    setSaving(true);
    setErrors({});
    setFormError(null);
    try {
      const updated = await productsApi.setAttributes(product.id, built.items);
      onDirtyChange(false);
      onProductChange(updated);
      setValues(valuesFromProduct(updated.attributes ?? []));
      toast.success('Характеристики сохранены');
    } catch (reason) {
      // 409 attribute_value_type_mismatch / attribute_option_owner_mismatch
      // приходят с attribute_id в деталях — показываем у нужного поля.
      const attributeId =
        reason instanceof ApiError && typeof reason.details?.attribute_id === 'number'
          ? reason.details.attribute_id
          : null;
      if (attributeId !== null) setErrors({ [attributeId]: describeError(reason) });
      else setFormError(describeError(reason));
      toast.error(
        isForbidden(reason) ? 'Нет права изменять товар' : 'Характеристики не сохранены',
        reason,
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={onSubmit} noValidate>
      <Card
        title="Характеристики"
        description={
          categoryIds.length === 0
            ? 'У товара нет категорий — назначьте их, чтобы появился набор характеристик.'
            : 'Набор характеристик задаётся категориями товара.'
        }
      >
        {formError ? (
          <div className={styles.formAlert} role="alert">
            {formError}
          </div>
        ) : null}
        <AttributeEditor
          defs={defs.data}
          loading={defs.status === 'loading'}
          error={defs.status === 'error' ? defs.error : undefined}
          onRetry={defs.reload}
          values={values}
          errors={errors}
          disabled={!canWrite || saving}
          onChange={(id, value) => setValues((state) => ({ ...state, [id]: value }))}
        />
        {canWrite && list.length > 0 ? (
          <SectionActions
            dirty={dirty}
            saving={saving}
            onReset={() => {
              setValues(initial);
              setErrors({});
              setFormError(null);
            }}
            note="Пустые значения не сохраняются."
          />
        ) : null}
      </Card>
    </form>
  );
}
