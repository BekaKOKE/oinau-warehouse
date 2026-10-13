'use client';

/**
 * Цвета товара: в каких цветах продаётся, остаток и надбавка по каждому.
 *
 * Остаток цвета — ручная разбивка общего остатка по складам, а не его
 * замена: наличие товара и обмен с 1С по-прежнему считаются по складам.
 * Поэтому экран показывает обе суммы и предупреждает о расхождении,
 * но ничего не подгоняет сам.
 *
 * На сайте точные количества не видны: только статус каждого цвета.
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
import { colorsApi, productColorsApi } from '@/lib/api/endpoints';
import type { Color, ProductColors } from '@/lib/api/types';
import { Permission } from '@/lib/auth/permissions';
import {
  addableColors,
  buildColorItems,
  draftFromColors,
  isColorDraftDirty,
  totalsMismatch,
  type ColorDraftRow,
} from '@/lib/colors';
import { formatQuantity } from '@/lib/decimal';
import { isForbidden } from '@/lib/errors';
import { unitLabel } from '@/lib/format';
import { useQuery } from '@/lib/hooks/useQuery';
import { AVAILABILITY } from '@/lib/labels';

import type { SectionProps } from '../ProductEditorScreen';
import styles from '../ProductEditor.module.css';
import { SectionActions } from './SectionActions';

export function ColorsSection({ product, canWrite, onDirtyChange }: SectionProps) {
  const { can } = useSession();
  // Цвет несёт и остаток, и надбавку к цене — нужны оба права.
  const editable = canWrite && can(Permission.STOCK_WRITE, Permission.PRICE_WRITE);
  const colors = useQuery((signal) => productColorsApi.get(product.id, { signal }), [product.id]);
  const palette = useQuery((signal) => colorsApi.list({ signal }), []);

  if (
    (colors.status === 'error' && !colors.data) ||
    (palette.status === 'error' && !palette.data)
  ) {
    return (
      <Card title="Цвета">
        <ErrorState
          error={colors.error ?? palette.error}
          onRetry={() => {
            colors.reload();
            palette.reload();
          }}
          compact
        />
      </Card>
    );
  }
  if (!colors.data || !palette.data) {
    return (
      <Card title="Цвета">
        <div className={styles.skeletonStack} aria-busy="true">
          <Skeleton height={36} />
          <Skeleton height={90} />
        </div>
      </Card>
    );
  }
  return (
    <ColorsEditor
      key={JSON.stringify(colors.data.items)}
      colors={colors.data}
      palette={palette.data}
      canEdit={editable}
      onSaved={colors.setData}
      onDirtyChange={onDirtyChange}
    />
  );
}

function Swatch({ hex, name }: { hex: string; name: string }) {
  return (
    <span className={styles.swatch} style={{ background: hex }} title={name} aria-hidden="true" />
  );
}

function ColorsEditor({
  colors,
  palette,
  canEdit,
  onSaved,
  onDirtyChange,
}: {
  colors: ProductColors;
  palette: Color[];
  canEdit: boolean;
  onSaved: (colors: ProductColors) => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const toast = useToast();
  const initial = useMemo(() => draftFromColors(colors), [colors]);
  const [draft, setDraft] = useState<ColorDraftRow[]>(initial);
  const [adding, setAdding] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  const dirty = isColorDraftDirty(draft, initial);
  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);

  const byId = useMemo(() => new Map(palette.map((color) => [color.id, color])), [palette]);
  const saved = useMemo(
    () => new Map((colors.items ?? []).map((item) => [item.color_id, item])),
    [colors],
  );
  const options = addableColors(palette, draft);
  const unit = unitLabel(colors.unit);

  const update = (colorId: number, patch: Partial<ColorDraftRow>) =>
    setDraft((rows) => rows.map((row) => (row.colorId === colorId ? { ...row, ...patch } : row)));

  const add = () => {
    const id = Number(adding);
    if (!id) return;
    setDraft((rows) => [...rows, { colorId: id, quantity: '0', priceDelta: '0' }]);
    setAdding('');
  };

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canEdit || saving || !dirty) return;
    const { body, errors: nextErrors } = buildColorItems(draft);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;
    setSaving(true);
    try {
      const result = await productColorsApi.set(colors.product_id, body);
      onDirtyChange(false);
      onSaved(result);
      toast.success('Цвета сохранены');
    } catch (error) {
      toast.error(isForbidden(error) ? 'Нет права изменять цвета' : 'Цвета не сохранены', error);
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={onSubmit} noValidate>
      <Card
        title="Цвета"
        description="В каких цветах продаётся товар. Клиент выбирает цвет на сайте и видит его наличие, но не количество."
      >
        {draft.length === 0 ? (
          <EmptyState
            icon="tag"
            title="Цвета не заданы"
            description="Товар продаётся без выбора цвета. Добавьте цвета, если они есть."
            compact
          />
        ) : (
          <ul className={styles.colorList} aria-label="Цвета товара">
            {draft.map((row) => {
              const color = byId.get(row.colorId);
              const current = saved.get(row.colorId);
              const name = color?.name ?? current?.name ?? `Цвет ${row.colorId}`;
              return (
                <li key={row.colorId} className={styles.colorRow}>
                  <div className={styles.colorName}>
                    <Swatch hex={color?.hex ?? current?.hex ?? '#ffffff'} name={name} />
                    <span className={styles.strong}>{name}</span>
                    {color && !color.is_active ? <Badge tone="warning">Отключён</Badge> : null}
                  </div>
                  <Field
                    label={`Остаток, ${unit}`}
                    error={errors[`${row.colorId}.quantity`]}
                    className={styles.stockField}
                  >
                    <Input
                      inputMode="decimal"
                      aria-label={`Остаток: ${name}`}
                      value={row.quantity}
                      disabled={!canEdit || saving}
                      onChange={(event) => update(row.colorId, { quantity: event.target.value })}
                    />
                  </Field>
                  <Field
                    label="Надбавка, ₸"
                    error={errors[`${row.colorId}.priceDelta`]}
                    className={styles.stockField}
                  >
                    <Input
                      inputMode="decimal"
                      aria-label={`Надбавка: ${name}`}
                      value={row.priceDelta}
                      disabled={!canEdit || saving}
                      onChange={(event) => update(row.colorId, { priceDelta: event.target.value })}
                    />
                  </Field>
                  <div className={styles.colorStatus}>
                    {current ? (
                      <EnumBadge value={current.public_availability} meta={AVAILABILITY} />
                    ) : (
                      <span className={styles.muted}>Новый</span>
                    )}
                    {canEdit ? (
                      <Button
                        size="sm"
                        variant="dangerGhost"
                        icon="trash"
                        disabled={saving}
                        aria-label={`Убрать цвет ${name}`}
                        onClick={() =>
                          setDraft((rows) => rows.filter((item) => item.colorId !== row.colorId))
                        }
                      />
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
        )}

        {canEdit ? (
          <div className={styles.colorAdd}>
            <Select
              aria-label="Добавить цвет"
              options={options.map((color) => ({ value: String(color.id), label: color.name }))}
              placeholder={
                options.length ? 'Выберите цвет…' : 'Все цвета справочника уже добавлены'
              }
              value={adding}
              disabled={saving || options.length === 0}
              onChange={(event) => setAdding(event.target.value)}
            />
            <Button variant="secondary" icon="plus" disabled={!adding || saving} onClick={add}>
              Добавить
            </Button>
          </div>
        ) : null}

        {(colors.items ?? []).length > 0 ? (
          <div className={styles.stockTotals}>
            <span>
              По цветам:{' '}
              <strong className="num">
                {formatQuantity(colors.colors_total)} {unit}
              </strong>
              <span className={styles.muted}>
                {' '}
                · на складах свободно {formatQuantity(colors.stock_total)} {unit}
              </span>
            </span>
            {totalsMismatch(colors) ? (
              <p className={styles.colorWarning} role="status">
                <Icon name="alert" size={14} /> Сумма по цветам не совпадает с остатком на складах.
                Проверьте разбивку или остатки во вкладке «Наличие».
              </p>
            ) : null}
          </div>
        ) : null}

        <p className={styles.muted}>
          Надбавка прибавляется к каждой ступени цены. Базовая цена товара — цена самого дешёвого
          цвета. Новые цвета заводятся в разделе «Цвета».
        </p>

        {canEdit ? (
          <SectionActions
            dirty={dirty}
            saving={saving}
            onReset={() => {
              setDraft(initial);
              setErrors({});
            }}
          />
        ) : (
          <p className={styles.readOnlyNote}>
            <Icon name="lock" size={14} /> Изменять цвета может роль с правами «Изменение остатков»
            и «Изменение цен».
          </p>
        )}
      </Card>
    </form>
  );
}
