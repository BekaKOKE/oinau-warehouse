'use client';

/**
 * Цены товара в публичном прайс-листе.
 *
 * Тип и ступени заменяются одним PUT — backend меняет их одной
 * транзакцией. Суммы и количества остаются строками от поля ввода до
 * тела запроса; превью показывает, как цену увидит посетитель.
 */

import { useEffect, useMemo, useState, type FormEvent } from 'react';

import { Button } from '@/components/ui/Button';
import { Field, Input } from '@/components/ui/Field';
import { Card } from '@/components/ui/Layout';
import { ErrorState, Skeleton } from '@/components/ui/States';
import { useToast } from '@/components/ui/Toast';
import { pricingApi } from '@/lib/api/endpoints';
import type { PricingRead, PricingType } from '@/lib/api/types';
import { currencySymbol } from '@/lib/decimal';
import { describeError, extractFieldErrors, isForbidden } from '@/lib/errors';
import { unitLabel } from '@/lib/format';
import { useQuery } from '@/lib/hooks/useQuery';
import { PRICING_TYPE } from '@/lib/labels';
import {
  MAX_TIERS,
  newTierRow,
  previewPrice,
  rowsFromTiers,
  validatePricing,
  type TierErrors,
  type TierRow,
} from '@/lib/pricing';

import type { SectionProps } from '../ProductEditorScreen';
import styles from '../ProductEditor.module.css';
import { SectionActions } from './SectionActions';

const TYPE_HINTS: Record<PricingType, string> = {
  FIXED: 'Одна цена за единицу при любом количестве.',
  FROM: 'На сайте — «от» минимальной ступени, без таблицы.',
  TIERED: 'Таблица цен по количеству; на сайте — «от» и таблица.',
  ON_REQUEST: 'Цены нет: клиент запрашивает её в заявке.',
};

const PRICING_TYPES = Object.keys(PRICING_TYPE) as PricingType[];

type EditorState = { type: PricingType; rows: TierRow[] };

function stateFromPricing(pricing: PricingRead): EditorState {
  const rows = rowsFromTiers(pricing.tiers ?? []);
  return {
    type: pricing.pricing_type,
    rows: rows.length > 0 ? rows : [newTierRow({ minQty: '1' })],
  };
}

function signature(state: EditorState): string {
  const result = validatePricing(state.type, state.rows);
  return result.ok ? JSON.stringify(result.payload) : `invalid:${JSON.stringify(state)}`;
}

export function PricingSection({ product, canWrite, onDirtyChange }: SectionProps) {
  const pricing = useQuery((signal) => pricingApi.get(product.id, { signal }), [product.id]);

  if (pricing.status === 'error' && !pricing.data) {
    return (
      <Card title="Цены">
        <ErrorState error={pricing.error} onRetry={pricing.reload} compact />
      </Card>
    );
  }
  if (!pricing.data) {
    return (
      <Card title="Цены">
        <div className={styles.skeletonStack} aria-busy="true">
          <Skeleton height={36} />
          <Skeleton height={120} />
        </div>
      </Card>
    );
  }
  return (
    <PricingEditor
      key={JSON.stringify(pricing.data)}
      pricing={pricing.data}
      unit={product.unit}
      canWrite={canWrite}
      onSaved={pricing.setData}
      onDirtyChange={onDirtyChange}
    />
  );
}

function PricingEditor({
  pricing,
  unit,
  canWrite,
  onSaved,
  onDirtyChange,
}: {
  pricing: PricingRead;
  unit: string;
  canWrite: boolean;
  onSaved: (pricing: PricingRead) => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const toast = useToast();
  const initial = useMemo(() => stateFromPricing(pricing), [pricing]);
  const [state, setState] = useState<EditorState>(initial);
  const [rowErrors, setRowErrors] = useState<Record<string, TierErrors>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const dirty = signature(state) !== signature(initial);
  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);

  const validation = validatePricing(state.type, state.rows);
  const preview = validation.ok ? previewPrice(validation.payload, unit, pricing.currency) : null;
  const symbol = currencySymbol(pricing.currency);

  const setRow = (key: string, patch: Partial<TierRow>) =>
    setState((current) => ({
      ...current,
      rows: current.rows.map((row) => (row.key === key ? { ...row, ...patch } : row)),
    }));

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canWrite || saving) return;
    const result = validatePricing(state.type, state.rows);
    if (!result.ok) {
      setRowErrors(result.rows);
      setFormError(result.form ?? null);
      return;
    }
    setSaving(true);
    setRowErrors({});
    setFormError(null);
    try {
      const saved = await pricingApi.set(pricing.product_id, result.payload);
      onDirtyChange(false);
      onSaved(saved);
      toast.success('Цены сохранены');
    } catch (error) {
      const fields = extractFieldErrors(error);
      setFormError(fields._form ?? Object.values(fields)[0] ?? describeError(error));
      toast.error(isForbidden(error) ? 'Нет права изменять цены' : 'Цены не сохранены', error);
    } finally {
      setSaving(false);
    }
  };

  const disabled = !canWrite || saving;
  const fixedRow = state.rows[0];

  return (
    <form onSubmit={onSubmit} noValidate className={styles.pricingLayout}>
      <Card
        title="Цены"
        description={`Публичный прайс-лист «${pricing.price_list_code}», валюта ${pricing.currency}.`}
      >
        {formError ? (
          <div className={styles.formAlert} role="alert">
            {formError}
          </div>
        ) : null}

        <fieldset className={styles.typeSwitch} disabled={disabled}>
          <legend className={styles.subheading}>Тип цены</legend>
          <div className={styles.typeOptions}>
            {PRICING_TYPES.map((type) => (
              <label
                key={type}
                className={`${styles.typeOption} ${state.type === type ? styles.typeOptionActive : ''}`}
              >
                <input
                  type="radio"
                  name="pricing-type"
                  value={type}
                  checked={state.type === type}
                  onChange={() => {
                    setState((current) => ({ ...current, type }));
                    setRowErrors({});
                    setFormError(null);
                  }}
                />
                <span className={styles.strong}>{PRICING_TYPE[type]}</span>
                <span className={styles.muted}>{TYPE_HINTS[type]}</span>
              </label>
            ))}
          </div>
        </fieldset>

        {state.type === 'FIXED' && fixedRow ? (
          <Field
            label={`Цена за ${unitLabel(unit)}, ${symbol}`}
            error={rowErrors[fixedRow.key]?.price}
            className={styles.priceField}
          >
            <Input
              name="fixed-price"
              inputMode="decimal"
              value={fixedRow.price}
              disabled={disabled}
              onChange={(event) => setRow(fixedRow.key, { price: event.target.value })}
            />
          </Field>
        ) : null}

        {state.type === 'FROM' || state.type === 'TIERED' ? (
          <div className={styles.tiers}>
            <div className={styles.tierHeader} aria-hidden="true">
              <span>От, {unitLabel(unit)}</span>
              <span>До, {unitLabel(unit)}</span>
              <span>Цена, {symbol}</span>
              <span />
            </div>
            <ol className={styles.tierList}>
              {state.rows.map((row, index) => {
                const errors = rowErrors[row.key] ?? {};
                return (
                  <li key={row.key} className={styles.tierRow}>
                    <Field
                      label={`Ступень ${index + 1}: от`}
                      error={errors.minQty}
                      className={styles.tierField}
                    >
                      <Input
                        inputMode="decimal"
                        value={row.minQty}
                        disabled={disabled}
                        onChange={(event) => setRow(row.key, { minQty: event.target.value })}
                      />
                    </Field>
                    <Field
                      label="до"
                      error={errors.maxQty}
                      className={styles.tierField}
                      hint={row.maxQty ? undefined : 'и более'}
                    >
                      <Input
                        inputMode="decimal"
                        placeholder="∞"
                        value={row.maxQty}
                        disabled={disabled}
                        onChange={(event) => setRow(row.key, { maxQty: event.target.value })}
                      />
                    </Field>
                    <Field label="цена" error={errors.price} className={styles.tierField}>
                      <Input
                        inputMode="decimal"
                        value={row.price}
                        disabled={disabled}
                        onChange={(event) => setRow(row.key, { price: event.target.value })}
                      />
                    </Field>
                    <Button
                      size="sm"
                      variant="dangerGhost"
                      icon="trash"
                      aria-label={`Удалить ступень ${index + 1}`}
                      disabled={disabled || state.rows.length === 1}
                      onClick={() =>
                        setState((current) => ({
                          ...current,
                          rows: current.rows.filter((item) => item.key !== row.key),
                        }))
                      }
                    />
                  </li>
                );
              })}
            </ol>
            {canWrite ? (
              <Button
                size="sm"
                icon="plus"
                disabled={disabled || state.rows.length >= MAX_TIERS}
                onClick={() =>
                  setState((current) => ({ ...current, rows: [...current.rows, newTierRow()] }))
                }
              >
                Добавить ступень
              </Button>
            ) : null}
            <p className={styles.muted}>
              Границы включительные: 1–9 и 10–49 — соседние ступени. Пустое «до» — «и более».
            </p>
          </div>
        ) : null}

        {canWrite ? (
          <SectionActions
            dirty={dirty}
            saving={saving}
            onReset={() => {
              setState(initial);
              setRowErrors({});
              setFormError(null);
            }}
          />
        ) : null}
      </Card>

      <Card title="Как увидит посетитель" className={styles.previewCard}>
        {preview ? (
          <div className={styles.preview} aria-live="polite">
            <p className={styles.previewHeadline} data-testid="price-preview">
              {preview.headline}
            </p>
            {preview.table.length > 0 ? (
              <table className={styles.previewTable}>
                <thead>
                  <tr>
                    <th scope="col">Количество</th>
                    <th scope="col">Цена за {unitLabel(unit)}</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.table.map((row) => (
                    <tr key={row.range}>
                      <td>{row.range}</td>
                      <td className="num">{row.price}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
          </div>
        ) : (
          <p className={styles.muted}>Исправьте ошибки, чтобы увидеть превью.</p>
        )}
      </Card>
    </form>
  );
}
