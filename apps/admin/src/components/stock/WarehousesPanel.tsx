'use client';

/**
 * Справочник складов.
 *
 * Правила backend: код задаётся один раз (по нему сопоставляются остатки
 * из 1С), удаления нет — склад отключается. Отключённый склад не входит
 * в наличие на сайте, и остатки на нём нельзя менять.
 */

import { useMemo, useState, type FormEvent } from 'react';

import { useSession } from '@/components/session/SessionProvider';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { Dialog, useConfirm } from '@/components/ui/Dialog';
import { Field, Input, Select, Switch } from '@/components/ui/Field';
import { Icon } from '@/components/ui/Icon';
import { Card } from '@/components/ui/Layout';
import { Pagination } from '@/components/ui/Pagination';
import { EmptyState } from '@/components/ui/States';
import { useToast } from '@/components/ui/Toast';
import { regionsApi, warehousesApi } from '@/lib/api/endpoints';
import type { Warehouse } from '@/lib/api/types';
import { Permission } from '@/lib/auth/permissions';
import { isForbidden, isNotFound } from '@/lib/errors';
import { formatCount, plural } from '@/lib/format';
import { useQuery } from '@/lib/hooks/useQuery';
import {
  buildWarehouseCreate,
  buildWarehouseUpdate,
  EMPTY_WAREHOUSE_FORM,
  formFromWarehouse,
  syncSourceMeta,
  validateWarehouseForm,
  warehouseErrorsFromApi,
  type WarehouseForm,
  type WarehouseFormErrors,
} from '@/lib/stock';

import styles from './Stock.module.css';

const PAGE_SIZE = 24;

const STATUS_OPTIONS = [
  { value: 'true', label: 'Активные' },
  { value: 'false', label: 'Отключённые' },
];

function StatusBadge({ warehouse }: { warehouse: Warehouse }) {
  return warehouse.is_active ? (
    <Badge tone="success">Активен</Badge>
  ) : (
    <Badge tone="warning">Отключён</Badge>
  );
}

export function WarehousesPanel() {
  const { can } = useSession();
  const canWrite = can(Permission.STOCK_WRITE);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<'' | 'true' | 'false'>('');
  const [open, setOpen] = useState<Warehouse | 'new' | null>(null);

  const query = useMemo(
    () => ({
      page,
      page_size: PAGE_SIZE,
      is_active: status ? status === 'true' : undefined,
    }),
    [page, status],
  );
  const list = useQuery((signal) => warehousesApi.list(query, { signal }), [JSON.stringify(query)]);

  const columns: Column<Warehouse>[] = [
    {
      key: 'name',
      header: 'Склад',
      cell: (row) => (
        <div className={styles.stack}>
          <span className={styles.strong}>{row.name}</span>
          <span className={`mono ${styles.muted}`}>{row.code}</span>
        </div>
      ),
    },
    {
      key: 'region',
      header: 'Регион',
      hideOnMobile: true,
      cell: (row) => row.region_name ?? <span className={styles.muted}>—</span>,
    },
    {
      key: 'external',
      header: 'Код во внешней системе',
      hideOnMobile: true,
      cell: (row) =>
        row.external_id ? (
          <span className="mono">{row.external_id}</span>
        ) : (
          <span className={styles.muted}>—</span>
        ),
    },
    {
      key: 'source',
      header: 'Источник',
      hideOnMobile: true,
      cell: (row) => {
        const meta = syncSourceMeta(row.sync_source);
        return <Badge tone={meta.tone}>{meta.label}</Badge>;
      },
    },
    { key: 'status', header: 'Статус', cell: (row) => <StatusBadge warehouse={row} /> },
    {
      key: 'actions',
      header: <span className="visually-hidden">Действия</span>,
      align: 'right',
      cell: (row) =>
        canWrite ? (
          <Button
            size="sm"
            variant="ghost"
            icon="edit"
            aria-label={`Изменить склад «${row.name}»`}
            onClick={(event) => {
              event.stopPropagation();
              setOpen(row);
            }}
          >
            Изменить
          </Button>
        ) : null,
    },
  ];

  const data = list.data;

  return (
    <>
      <Card flush>
        <div className={styles.warehouseFilters}>
          <Field label="Статус склада">
            <Select
              options={STATUS_OPTIONS}
              placeholder="Все"
              value={status}
              onChange={(event) => {
                setStatus(event.target.value as '' | 'true' | 'false');
                setPage(1);
              }}
            />
          </Field>
          <span className={`${styles.muted} ${styles.grow}`}>
            {data
              ? `${formatCount(data.total)} ${plural(data.total, ['склад', 'склада', 'складов'])}. `
              : null}
            Склады не удаляются — отключённый склад не входит в наличие на сайте.
          </span>
          {canWrite ? (
            <Button variant="primary" icon="plus" onClick={() => setOpen('new')}>
              Новый склад
            </Button>
          ) : null}
        </div>
        <DataTable
          caption="Склады"
          columns={columns}
          rows={data?.items}
          rowKey={(row) => row.id}
          loading={list.status === 'loading'}
          refreshing={list.isRefreshing}
          error={list.status === 'error' ? list.error : undefined}
          onRetry={list.reload}
          onRowClick={canWrite ? (row) => setOpen(row) : undefined}
          empty={
            <EmptyState
              icon="stock"
              title={status ? 'Таких складов нет' : 'Складов пока нет'}
              description={
                canWrite && !status ? 'Создайте склад, чтобы вести остатки товаров.' : undefined
              }
              compact
            />
          }
          renderMobile={(row) => (
            <div className={styles.mobileCard}>
              <div className={styles.mobileTop}>
                <div className={styles.stack}>
                  <span className={styles.strong}>{row.name}</span>
                  <span className={`mono ${styles.muted}`}>{row.code}</span>
                </div>
                <StatusBadge warehouse={row} />
              </div>
              <span className={styles.muted}>
                {row.region_name ?? 'Без региона'}
                {row.external_id ? ` · ${row.external_id}` : ''} ·{' '}
                {syncSourceMeta(row.sync_source).label}
              </span>
            </div>
          )}
        />
        {data ? (
          <Pagination
            page={data.page}
            pages={data.pages}
            total={data.total}
            pageSize={PAGE_SIZE}
            disabled={list.isRefreshing}
            onPageChange={setPage}
          />
        ) : null}
      </Card>

      {open !== null && canWrite ? (
        <WarehouseDialog
          key={open === 'new' ? 'new' : open.id}
          warehouse={open === 'new' ? null : open}
          onClose={() => setOpen(null)}
          onSaved={() => {
            setOpen(null);
            list.reload();
          }}
          onStale={list.reload}
        />
      ) : null}
    </>
  );
}

function WarehouseDialog({
  warehouse,
  onClose,
  onSaved,
  onStale,
}: {
  warehouse: Warehouse | null;
  onClose: () => void;
  onSaved: () => void;
  onStale: () => void;
}) {
  const toast = useToast();
  const confirm = useConfirm();
  const creating = warehouse === null;
  const initial = useMemo(
    () => (warehouse ? formFromWarehouse(warehouse) : EMPTY_WAREHOUSE_FORM),
    [warehouse],
  );
  const [form, setForm] = useState<WarehouseForm>(initial);
  const [errors, setErrors] = useState<WarehouseFormErrors>({});
  const [saving, setSaving] = useState(false);
  const regions = useQuery((signal) => regionsApi.list({ signal }), []);

  const regionOptions = (regions.data ?? []).map((region) => ({
    value: String(region.id),
    label: region.name,
  }));
  // Регион склада мог быть отключён и пропасть из публичного справочника.
  if (warehouse?.region_id && !regionOptions.some((o) => o.value === String(warehouse.region_id))) {
    regionOptions.push({
      value: String(warehouse.region_id),
      label: warehouse.region_name ?? `Регион ${warehouse.region_id}`,
    });
  }

  const set = (patch: Partial<WarehouseForm>) => setForm((state) => ({ ...state, ...patch }));
  const payload = creating ? null : buildWarehouseUpdate(form, initial);
  const dirty = creating || Object.keys(payload ?? {}).length > 0;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (saving) return;
    const local = validateWarehouseForm(form, creating);
    setErrors(local);
    if (Object.keys(local).length > 0) return;
    if (!creating && initial.isActive && !form.isActive) {
      const approved = await confirm({
        title: `Отключить склад «${warehouse.name}»?`,
        description:
          'Остатки на нём перестанут учитываться в наличии на сайте, а менять их станет нельзя. Данные не удаляются — склад можно включить обратно.',
        confirmLabel: 'Отключить',
      });
      if (!approved) return;
    }
    setSaving(true);
    try {
      if (creating) {
        const created = await warehousesApi.create(buildWarehouseCreate(form));
        toast.success('Склад создан', created.name);
      } else {
        if (!payload || Object.keys(payload).length === 0) return;
        await warehousesApi.update(warehouse.id, payload);
        toast.success('Склад сохранён');
      }
      onSaved();
    } catch (error) {
      setErrors(warehouseErrorsFromApi(error));
      toast.error(
        isForbidden(error)
          ? 'Нет права изменять склады'
          : isNotFound(error)
            ? 'Склад не найден'
            : creating
              ? 'Склад не создан'
              : 'Склад не сохранён',
        error,
      );
      if (isNotFound(error)) onStale();
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open
      onClose={onClose}
      busy={saving}
      title={creating ? 'Новый склад' : `Склад «${warehouse.name}»`}
      description={
        creating ? 'Код задаётся один раз: по нему будут сопоставляться остатки из 1С.' : undefined
      }
    >
      <form onSubmit={submit} noValidate className={styles.section}>
        {errors._form ? (
          <div className={styles.formAlert} role="alert">
            {errors._form}
          </div>
        ) : null}
        <div className={styles.formGrid}>
          <Field label="Название" required error={errors.name} className={styles.wide}>
            <Input
              name="name"
              maxLength={255}
              value={form.name}
              disabled={saving}
              onChange={(event) => set({ name: event.target.value })}
            />
          </Field>
          {creating ? (
            <Field
              label="Код"
              required
              error={errors.code}
              hint="Строчная латиница, цифры, «-» и «_». Потом не меняется."
            >
              <Input
                name="code"
                className="mono"
                maxLength={64}
                value={form.code}
                disabled={saving}
                onChange={(event) => set({ code: event.target.value })}
              />
            </Field>
          ) : (
            <div className={styles.readonlyCode} data-testid="warehouse-code">
              <span className={styles.muted}>Код</span>
              <span className="mono">{form.code}</span>
              <span className={styles.lockHint}>
                <Icon name="lock" size={12} /> Не меняется: по нему сопоставляются остатки
              </span>
            </div>
          )}
          <Field label="Код во внешней системе" error={errors.externalId} hint="Например, код в 1С">
            <Input
              name="externalId"
              className="mono"
              maxLength={64}
              value={form.externalId}
              disabled={saving}
              onChange={(event) => set({ externalId: event.target.value })}
            />
          </Field>
          <Field label="Регион" error={errors.regionId}>
            <Select
              name="regionId"
              options={regionOptions}
              placeholder={regions.status === 'loading' ? 'Загружаем регионы…' : 'Без региона'}
              value={form.regionId}
              disabled={saving}
              onChange={(event) => set({ regionId: event.target.value })}
            />
          </Field>
          <div className={styles.wide}>
            <Switch
              label="Активен"
              description="Отключённый склад не входит в наличие на сайте, остатки на нём не меняются."
              checked={form.isActive}
              disabled={saving}
              onChange={(event) => set({ isActive: event.target.checked })}
            />
          </div>
        </div>
        <div className={styles.actions}>
          <Button variant="ghost" disabled={saving} onClick={onClose}>
            Отмена
          </Button>
          <Button type="submit" variant="primary" loading={saving} disabled={!dirty}>
            {creating ? 'Создать' : 'Сохранить'}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
