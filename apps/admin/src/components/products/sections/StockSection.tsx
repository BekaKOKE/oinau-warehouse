'use client';

/**
 * Остатки и показ наличия — две разные вещи, и экран их не смешивает:
 *
 * 1. Фактические остатки по складам (quantity / reserved). Сейчас
 *    правятся вручную; после интеграции источником истины станет 1С,
 *    и ручная правка останется аварийным инструментом.
 * 2. Переопределение показа на сайте — только то, что видит посетитель.
 *    Остатки при этом не меняются.
 *
 * Точные количества на сайт не попадают: витрина знает только статус.
 */

import { useEffect, useMemo, useState, type FormEvent } from 'react';

import { useSession } from '@/components/session/SessionProvider';
import { Badge, EnumBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Field, Input, Select } from '@/components/ui/Field';
import { Icon } from '@/components/ui/Icon';
import { Card } from '@/components/ui/Layout';
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/States';
import { useToast } from '@/components/ui/Toast';
import { productStockApi } from '@/lib/api/endpoints';
import type { ProductStock, StockDisplayOverride, StockEntry } from '@/lib/api/types';
import { Permission } from '@/lib/auth/permissions';
import { formatQuantity } from '@/lib/decimal';
import { describeError, isForbidden } from '@/lib/errors';
import { formatDateTime, unitLabel } from '@/lib/format';
import { useQuery } from '@/lib/hooks/useQuery';
import { AVAILABILITY } from '@/lib/labels';
import {
  buildStockItems,
  changedEntries,
  draftFromStock,
  OVERRIDE_OPTIONS,
  stockErrorsFromApi,
  syncSourceMeta,
  type StockDraft,
} from '@/lib/stock';

import type { SectionProps } from '../ProductEditorScreen';
import styles from '../ProductEditor.module.css';
import { SectionActions } from './SectionActions';

export function StockSection({ product, canWrite, onDirtyChange }: SectionProps) {
  const { can } = useSession();
  const stockWrite = canWrite && can(Permission.STOCK_WRITE);
  const stock = useQuery((signal) => productStockApi.get(product.id, { signal }), [product.id]);

  if (stock.status === 'error' && !stock.data) {
    return (
      <Card title="Наличие">
        <ErrorState error={stock.error} onRetry={stock.reload} compact />
      </Card>
    );
  }
  if (!stock.data) {
    return (
      <Card title="Наличие">
        <div className={styles.skeletonStack} aria-busy="true">
          <Skeleton height={36} />
          <Skeleton height={90} />
        </div>
      </Card>
    );
  }
  return (
    <div className={styles.stockLayout}>
      <StockEditor
        key={JSON.stringify(stock.data.entries)}
        stock={stock.data}
        canEdit={stockWrite}
        onSaved={stock.setData}
        onDirtyChange={onDirtyChange}
      />
      <OverrideEditor
        stock={stock.data}
        canEdit={stockWrite}
        onSaved={(patch) => stock.setData({ ...stock.data!, ...patch })}
      />
    </div>
  );
}

function StockEditor({
  stock,
  canEdit,
  onSaved,
  onDirtyChange,
}: {
  stock: ProductStock;
  canEdit: boolean;
  onSaved: (stock: ProductStock) => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const toast = useToast();
  const initial = useMemo(() => draftFromStock(stock), [stock]);
  const [draft, setDraft] = useState<StockDraft>(initial);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const entries = stock.entries ?? [];

  const changed = changedEntries(entries, draft, initial);
  const dirty = changed.length > 0;
  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canEdit || saving || !dirty) return;
    const { items, errors: nextErrors } = buildStockItems(changed, draft);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;
    setSaving(true);
    setFormError(null);
    try {
      const saved = await productStockApi.set(stock.product_id, { items });
      onDirtyChange(false);
      onSaved(saved);
      toast.success('Остатки сохранены');
    } catch (error) {
      const mapped = stockErrorsFromApi(error, items);
      setErrors(mapped.fields);
      setFormError(
        mapped.form ?? (Object.keys(mapped.fields).length ? null : describeError(error)),
      );
      toast.error(
        isForbidden(error) ? 'Нет права изменять остатки' : 'Остатки не сохранены',
        error,
      );
    } finally {
      setSaving(false);
    }
  };

  const unit = unitLabel(stock.unit);

  const renderEntry = (entry: StockEntry) => {
    const value = draft[entry.warehouse_id] ?? { quantity: '', reserved: '' };
    const editable = canEdit && entry.warehouse_is_active;
    return (
      <li key={entry.warehouse_id} className={styles.stockRow}>
        <div className={styles.stockWarehouse}>
          <span className={styles.strong}>{entry.warehouse_name}</span>
          <span className={styles.muted}>
            <span className="mono">{entry.warehouse_code}</span>
            {entry.warehouse_is_active ? null : (
              <>
                {' '}
                <Badge tone="warning">Склад отключён</Badge>
              </>
            )}
          </span>
        </div>
        {editable ? (
          <>
            <Field
              label={`Остаток, ${unit}`}
              error={errors[`${entry.warehouse_id}.quantity`]}
              className={styles.stockField}
            >
              <Input
                inputMode="decimal"
                value={value.quantity}
                disabled={saving}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    [entry.warehouse_id]: { ...value, quantity: event.target.value },
                  }))
                }
              />
            </Field>
            <Field
              label={`Резерв, ${unit}`}
              error={errors[`${entry.warehouse_id}.reserved`]}
              className={styles.stockField}
            >
              <Input
                inputMode="decimal"
                value={value.reserved}
                disabled={saving}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    [entry.warehouse_id]: { ...value, reserved: event.target.value },
                  }))
                }
              />
            </Field>
          </>
        ) : (
          <dl className={styles.stockNumbers}>
            <div>
              <dt>Остаток</dt>
              <dd className="num">
                {formatQuantity(entry.quantity)} {unit}
              </dd>
            </div>
            <div>
              <dt>Резерв</dt>
              <dd className="num">
                {formatQuantity(entry.reserved)} {unit}
              </dd>
            </div>
          </dl>
        )}
        <dl className={styles.stockNumbers}>
          <div>
            <dt>Свободно</dt>
            <dd className={`num ${styles.strong}`}>
              {formatQuantity(entry.available)} {unit}
            </dd>
          </div>
          <div>
            <dt>Источник</dt>
            <dd>
              {entry.sync_source ? syncSourceMeta(entry.sync_source).label : '—'}
              {entry.external_id ? (
                <span className={`mono ${styles.muted}`}> · {entry.external_id}</span>
              ) : null}
            </dd>
          </div>
          <div>
            <dt>Обновлено</dt>
            <dd className={styles.muted}>
              {entry.synced_at
                ? `1С: ${formatDateTime(entry.synced_at)}`
                : formatDateTime(entry.updated_at)}
            </dd>
          </div>
        </dl>
      </li>
    );
  };

  return (
    <form onSubmit={onSubmit} noValidate>
      <Card
        title="Остатки на складах"
        description="Точные количества видят только сотрудники. На сайте — лишь статус наличия."
      >
        <div className={styles.sourceNote}>
          <Icon name="info" size={14} />
          <span>
            Сейчас остатки задаются вручную. После подключения 1С источником истины станет учётная
            система, и её данные будут перезаписывать ручные значения.
          </span>
        </div>

        {formError ? (
          <div className={styles.formAlert} role="alert">
            {formError}
          </div>
        ) : null}

        {entries.length === 0 ? (
          <EmptyState
            icon="stock"
            title="Складов нет"
            description="Добавьте склад в разделе «Склад», чтобы вести остатки."
            compact
          />
        ) : (
          <ul className={styles.stockList}>{entries.map(renderEntry)}</ul>
        )}

        <div className={styles.stockTotals}>
          <span>
            Итого по активным складам:{' '}
            <strong className="num">
              {formatQuantity(stock.total_available)} {unit}
            </strong>{' '}
            свободно
            <span className={styles.muted}>
              {' '}
              (остаток {formatQuantity(stock.total_quantity)}, резерв{' '}
              {formatQuantity(stock.total_reserved)})
            </span>
          </span>
        </div>

        {canEdit && entries.length > 0 ? (
          <SectionActions
            dirty={dirty}
            saving={saving}
            onReset={() => {
              setDraft(initial);
              setErrors({});
              setFormError(null);
            }}
            note="Сохраняются только изменённые склады."
          />
        ) : null}
        {!canEdit ? (
          <p className={styles.readOnlyNote}>
            <Icon name="lock" size={14} /> Изменять остатки может роль с правом «Изменение
            остатков».
          </p>
        ) : null}
      </Card>
    </form>
  );
}

function OverrideEditor({
  stock,
  canEdit,
  onSaved,
}: {
  stock: ProductStock;
  canEdit: boolean;
  onSaved: (patch: Pick<ProductStock, 'stock_display_override' | 'public_availability'>) => void;
}) {
  const toast = useToast();
  const [value, setValue] = useState<StockDisplayOverride | ''>(stock.stock_display_override ?? '');
  const [saving, setSaving] = useState(false);
  const current = stock.stock_display_override ?? '';

  useEffect(() => setValue(stock.stock_display_override ?? ''), [stock.stock_display_override]);

  const save = async () => {
    setSaving(true);
    try {
      const saved = await productStockApi.setOverride(stock.product_id, value || null);
      onSaved({
        stock_display_override: saved.stock_display_override,
        public_availability: saved.public_availability,
      });
      toast.success('Показ наличия обновлён');
    } catch (error) {
      toast.error(isForbidden(error) ? 'Нет права изменять наличие' : 'Не сохранено', error);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card
      title="Наличие на сайте"
      description="Что видит посетитель. Остатки при этом не меняются."
    >
      <div className={styles.overrideBox}>
        <div className={styles.currentStatus}>
          <span className={styles.muted}>Сейчас на сайте</span>
          <EnumBadge value={stock.public_availability} meta={AVAILABILITY} />
        </div>
        <Field
          label="Показ наличия"
          hint={
            current
              ? 'Статус задан вручную и не зависит от остатков.'
              : 'Статус вычисляется по свободному остатку активных складов.'
          }
        >
          <Select
            options={OVERRIDE_OPTIONS.filter((option) => option.value !== '')}
            placeholder={OVERRIDE_OPTIONS[0]!.label}
            value={value}
            disabled={!canEdit || saving}
            onChange={(event) => setValue(event.target.value as StockDisplayOverride | '')}
          />
        </Field>
        {canEdit ? (
          <Button
            variant="secondary"
            loading={saving}
            disabled={value === current}
            onClick={() => void save()}
          >
            Применить
          </Button>
        ) : null}
      </div>
    </Card>
  );
}
