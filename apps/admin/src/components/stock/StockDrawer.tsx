'use client';

/**
 * Остатки товара в боковой панели.
 *
 * Два разных действия, которые нельзя смешивать:
 * 1. Фактические остатки по складам (PUT /products/{id}/stock) — числа
 *    склада. Сейчас правятся вручную, после 1С их будет присылать учётная
 *    система.
 * 2. Публичное наличие (PATCH /products/{id}/availability) — только то,
 *    что видит посетитель сайта. Остатки при этом не меняются.
 *
 * Свободный остаток и публичный статус считает backend: после сохранения
 * панель показывает данные из ответа сервера и перечитывает список.
 */

import { useEffect, useMemo, useState, type FormEvent } from 'react';

import { useSession } from '@/components/session/SessionProvider';
import { Badge, EnumBadge } from '@/components/ui/Badge';
import { Button, ButtonLink } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Field, Input, Select } from '@/components/ui/Field';
import { Icon } from '@/components/ui/Icon';
import { ErrorState, Skeleton } from '@/components/ui/States';
import { useToast } from '@/components/ui/Toast';
import { ApiError } from '@/lib/api/client';
import { productStockApi } from '@/lib/api/endpoints';
import type {
  ProductStock,
  ProductStockListItem,
  StockDisplayOverride,
  StockEntry,
  StockUpdate,
} from '@/lib/api/types';
import { Permission } from '@/lib/auth/permissions';
import { formatQuantity } from '@/lib/decimal';
import { describeError, isForbidden, isNotFound } from '@/lib/errors';
import { formatDateTime, unitLabel } from '@/lib/format';
import { useQuery } from '@/lib/hooks/useQuery';
import { useUnsavedGuard } from '@/lib/hooks/useUnsavedGuard';
import { AVAILABILITY } from '@/lib/labels';
import {
  availableTone,
  buildStockItems,
  changedEntries,
  draftFromStock,
  OVERRIDE_OPTIONS,
  stockErrorsFromApi,
  syncSourceMeta,
  type StockDraft,
} from '@/lib/stock';

import styles from './Stock.module.css';

type Props = {
  item: ProductStockListItem;
  onClose: () => void;
  onChanged: () => void;
};

export function StockDrawer({ item, onClose, onChanged }: Props) {
  const { can } = useSession();
  const canWrite = can(Permission.STOCK_WRITE);
  const stock = useQuery(
    (signal) => productStockApi.get(item.product_id, { signal }),
    [item.product_id],
  );
  const [busy, setBusy] = useState(false);

  return (
    <Dialog
      open
      variant="drawer"
      size="lg"
      onClose={onClose}
      busy={busy}
      title={item.name ?? item.sku}
      description={
        <span className={styles.inline}>
          <span className="mono">{item.sku}</span>
          {item.primary_category ? <span>· {item.primary_category.name}</span> : null}
          {item.external_id ? <span className="mono">· 1С: {item.external_id}</span> : null}
        </span>
      }
    >
      <div className={styles.drawerBody}>
        {stock.status === 'error' && !stock.data ? (
          isNotFound(stock.error) ? (
            <p className={styles.formAlert} role="alert">
              Товар не найден — возможно, он удалён. Обновите список.
            </p>
          ) : (
            <ErrorState error={stock.error} onRetry={stock.reload} compact />
          )
        ) : !stock.data ? (
          <div className={styles.section} aria-busy="true">
            <Skeleton height={80} />
            <Skeleton height={80} />
            <Skeleton height={60} />
          </div>
        ) : (
          <>
            <StockEditor
              key={JSON.stringify(stock.data.entries)}
              stock={stock.data}
              canWrite={canWrite}
              onBusy={setBusy}
              onSaved={(saved) => {
                stock.setData(saved);
                onChanged();
              }}
              onStale={() => {
                stock.reload();
                onChanged();
              }}
            />
            <PublicAvailability
              stock={stock.data}
              canWrite={canWrite}
              onBusy={setBusy}
              onSaved={() => {
                // Публичный статус пересчитывает backend — берём его ответ.
                stock.reload();
                onChanged();
              }}
            />
          </>
        )}
        <div className={styles.actions}>
          <ButtonLink
            href={`/products/${item.product_id}?tab=stock`}
            variant="ghost"
            icon="external"
          >
            Карточка товара
          </ButtonLink>
        </div>
      </div>
    </Dialog>
  );
}

// ================================================================ остатки

function StockEditor({
  stock,
  canWrite,
  onBusy,
  onSaved,
  onStale,
}: {
  stock: ProductStock;
  canWrite: boolean;
  onBusy: (busy: boolean) => void;
  onSaved: (stock: ProductStock) => void;
  onStale: () => void;
}) {
  const toast = useToast();
  const initial = useMemo(() => draftFromStock(stock), [stock]);
  const [draft, setDraft] = useState<StockDraft>(initial);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const entries = stock.entries ?? [];
  const editableCount = entries.filter((entry) => entry.warehouse_is_active).length;
  const changed = changedEntries(entries, draft, initial);
  const dirty = changed.length > 0;
  const unit = unitLabel(stock.unit);
  useUnsavedGuard(dirty && !saving);

  useEffect(() => onBusy(saving), [saving, onBusy]);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canWrite || saving || !dirty) return;
    const { items, errors: local } = buildStockItems(changed, draft);
    setErrors(local);
    setFormError(null);
    if (Object.keys(local).length > 0) return;
    await save(items);
  };

  const save = async (items: StockUpdate['items']) => {
    setSaving(true);
    try {
      const saved = await productStockApi.set(stock.product_id, { items });
      toast.success('Остатки сохранены', 'Свободный остаток и наличие пересчитаны сервером.');
      onSaved(saved);
    } catch (error) {
      if (error instanceof ApiError && error.status === 422) {
        const mapped = stockErrorsFromApi(error, items);
        setErrors(mapped.fields);
        setFormError(mapped.form ?? null);
        toast.error('Остатки не сохранены', error);
      } else if (error instanceof ApiError && error.code === 'warehouse_inactive') {
        setFormError('Склад отключён — остаток на нём менять нельзя. Данные обновлены.');
        toast.error('Склад отключён', error);
        onStale();
      } else if (error instanceof ApiError && error.code === 'product_deleted') {
        setFormError('Товар удалён — остатки удалённого товара не меняются.');
        toast.error('Товар удалён', error);
      } else if (isNotFound(error)) {
        setFormError(describeError(error));
        toast.error('Товар или склад не найден', error);
        onStale();
      } else {
        setFormError(describeError(error));
        toast.error(
          isForbidden(error) ? 'Нет права изменять остатки' : 'Остатки не сохранены',
          error,
        );
      }
    } finally {
      setSaving(false);
    }
  };

  const setValue = (warehouseId: number, patch: Partial<StockDraft[number]>) =>
    setDraft((current) => ({
      ...current,
      [warehouseId]: { quantity: '', reserved: '', ...current[warehouseId], ...patch },
    }));

  const renderEntry = (entry: StockEntry) => {
    const editable = canWrite && entry.warehouse_is_active;
    const value = draft[entry.warehouse_id] ?? { quantity: '', reserved: '' };
    const source = syncSourceMeta(entry.sync_source);
    const entryDirty = changed.some((item) => item.warehouse_id === entry.warehouse_id);
    return (
      <li
        key={entry.warehouse_id}
        className={`${styles.entry} ${entry.warehouse_is_active ? '' : styles.entryInactive}`}
        aria-label={`Склад «${entry.warehouse_name}»`}
      >
        <div className={styles.entryHead}>
          <div className={styles.stack}>
            <span className={styles.strong}>{entry.warehouse_name}</span>
            <span className={`mono ${styles.muted}`}>{entry.warehouse_code}</span>
          </div>
          <span className={styles.inline}>
            {entry.warehouse_is_active ? null : (
              <Badge tone="warning">Склад отключён — не входит в наличие</Badge>
            )}
            <Badge tone={source.tone}>{source.label}</Badge>
          </span>
        </div>

        <dl className={styles.metrics}>
          <div className={styles.metric}>
            <dt>Остаток</dt>
            <dd>
              {editable ? (
                <Field label={`Остаток, ${unit}`} error={errors[`${entry.warehouse_id}.quantity`]}>
                  <Input
                    className={styles.metricInput}
                    inputMode="decimal"
                    autoComplete="off"
                    value={value.quantity}
                    disabled={saving}
                    onChange={(event) =>
                      setValue(entry.warehouse_id, { quantity: event.target.value })
                    }
                  />
                </Field>
              ) : (
                `${formatQuantity(entry.quantity)} ${unit}`
              )}
            </dd>
          </div>
          <div className={styles.metric}>
            <dt>Резерв</dt>
            <dd>
              {editable ? (
                <Field label={`Резерв, ${unit}`} error={errors[`${entry.warehouse_id}.reserved`]}>
                  <Input
                    className={styles.metricInput}
                    inputMode="decimal"
                    autoComplete="off"
                    value={value.reserved}
                    disabled={saving}
                    onChange={(event) =>
                      setValue(entry.warehouse_id, { reserved: event.target.value })
                    }
                  />
                </Field>
              ) : (
                `${formatQuantity(entry.reserved)} ${unit}`
              )}
            </dd>
          </div>
          <div
            className={`${styles.metric} ${styles.metricAvailable} ${
              styles[`tone-${availableTone(entry.available)}`]
            }`}
          >
            <dt>Свободно</dt>
            <dd data-testid={`available-${entry.warehouse_id}`}>
              {formatQuantity(entry.available)} {unit}
            </dd>
            {entryDirty ? (
              <span className={styles.muted}>Пересчитается после сохранения</span>
            ) : null}
          </div>
        </dl>

        <dl className={styles.syncFacts}>
          <div>
            <dt>Код во внешней системе</dt>
            <dd className="mono">{entry.external_id ?? '—'}</dd>
          </div>
          <div>
            <dt>Синхронизация</dt>
            <dd>{entry.synced_at ? formatDateTime(entry.synced_at) : 'Не было'}</dd>
          </div>
          <div>
            <dt>Изменено</dt>
            <dd>{entry.updated_at ? formatDateTime(entry.updated_at) : '—'}</dd>
          </div>
        </dl>
      </li>
    );
  };

  return (
    <form onSubmit={onSubmit} noValidate className={styles.section} aria-labelledby="stock-facts">
      <p id="stock-facts" className={styles.sectionTitle}>
        Фактические остатки
      </p>
      {canWrite && editableCount > 0 ? (
        <div className={`${styles.note} ${styles.warningNote}`} role="note">
          <Icon name="alert" size={16} />
          <span>
            <strong>Ручное изменение используется до подключения 1C.</strong> После интеграции
            источником истины по остаткам станет учётная система, и её данные перезапишут ручные
            значения. Истории движений нет — задаётся текущее значение.
          </span>
        </div>
      ) : null}

      {formError ? (
        <div className={styles.formAlert} role="alert">
          {formError}
        </div>
      ) : null}

      {entries.length === 0 ? (
        <p className={styles.muted}>
          Складов нет. Добавьте склад на вкладке «Склады», чтобы вести остатки.
        </p>
      ) : (
        <ul className={styles.entryList}>{entries.map(renderEntry)}</ul>
      )}

      <p className={styles.totals}>
        Итого по активным складам: остаток{' '}
        <strong className="num">
          {formatQuantity(stock.total_quantity)} {unit}
        </strong>
        , резерв{' '}
        <strong className="num">
          {formatQuantity(stock.total_reserved)} {unit}
        </strong>
        , свободно{' '}
        <strong className="num" data-testid="total-available">
          {formatQuantity(stock.total_available)} {unit}
        </strong>
      </p>

      {canWrite && editableCount > 0 ? (
        <div className={`${styles.actions} ${styles.actionsSpread}`}>
          <span className={styles.muted}>
            {dirty ? 'Есть несохранённые изменения' : 'Сохраняются только изменённые склады.'}
          </span>
          <span className={styles.inline}>
            <Button
              variant="ghost"
              disabled={!dirty || saving}
              onClick={() => {
                setDraft(initial);
                setErrors({});
                setFormError(null);
              }}
            >
              Отменить
            </Button>
            <Button type="submit" variant="primary" loading={saving} disabled={!dirty}>
              Сохранить остатки
            </Button>
          </span>
        </div>
      ) : !canWrite ? (
        <p className={styles.readOnly}>
          <Icon name="lock" size={14} /> Только просмотр: изменять остатки может роль с правом
          «Изменение остатков».
        </p>
      ) : null}
    </form>
  );
}

// ==================================================== публичное наличие

function PublicAvailability({
  stock,
  canWrite,
  onBusy,
  onSaved,
}: {
  stock: ProductStock;
  canWrite: boolean;
  onBusy: (busy: boolean) => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const current = stock.stock_display_override ?? '';
  const [value, setValue] = useState<StockDisplayOverride | ''>(current);
  const [saving, setSaving] = useState(false);

  useEffect(() => setValue(stock.stock_display_override ?? ''), [stock.stock_display_override]);
  useEffect(() => onBusy(saving), [saving, onBusy]);

  const save = async () => {
    setSaving(true);
    try {
      await productStockApi.setOverride(stock.product_id, value || null);
      toast.success(
        value ? 'Показ наличия задан вручную' : 'Наличие снова считается по остаткам',
        'Остатки не изменились.',
      );
      onSaved();
    } catch (error) {
      toast.error(
        isForbidden(error)
          ? 'Нет права изменять наличие'
          : error instanceof ApiError && error.code === 'product_deleted'
            ? 'Товар удалён — наличие не меняется'
            : 'Наличие не изменено',
        error,
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className={styles.section} aria-labelledby="public-availability">
      <p id="public-availability" className={styles.sectionTitle}>
        Публичное наличие
      </p>
      <div className={styles.note}>
        <Icon name="info" size={16} />
        <div>
          Фактический остаток и публичное наличие — разные вещи.
          <ul className={styles.noteList}>
            <li>Переопределение не меняет остаток и резерв.</li>
            <li>
              Оно влияет только на статус, который посетитель видит на сайте. Без него статус
              вычисляется по свободному остатку активных складов и типу цены.
            </li>
            <li>Точные количества на сайт не попадают никогда.</li>
          </ul>
        </div>
      </div>
      <div className={styles.currentStatus}>
        <span className={styles.muted}>Сейчас на сайте:</span>
        <EnumBadge value={stock.public_availability} meta={AVAILABILITY} />
        {current ? <Badge tone="warning">Задано вручную</Badge> : <Badge>По остаткам</Badge>}
      </div>
      <div className={styles.overrideBox}>
        <Field
          label="Показ наличия"
          hint={
            current
              ? 'Статус задан вручную и не зависит от остатков.'
              : 'Статус вычисляется автоматически.'
          }
        >
          <Select
            options={OVERRIDE_OPTIONS.filter((option) => option.value !== '')}
            placeholder={OVERRIDE_OPTIONS[0]!.label}
            value={value}
            disabled={!canWrite || saving}
            onChange={(event) => setValue(event.target.value as StockDisplayOverride | '')}
          />
        </Field>
        {canWrite ? (
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
    </section>
  );
}
