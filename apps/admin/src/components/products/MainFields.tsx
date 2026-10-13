'use client';

/**
 * Основные поля товара — общие для создания и редактирования.
 */

import { Button } from '@/components/ui/Button';
import { Field, Input, Select, Switch, Textarea } from '@/components/ui/Field';
import { enumOptions, PRODUCT_STATUS } from '@/lib/labels';
import { unitLabel } from '@/lib/format';
import type { MainForm, MainFormErrors } from '@/lib/productForm';
import { slugFromName } from '@/lib/products';

import styles from './ProductEditor.module.css';

const STATUS_OPTIONS = enumOptions(PRODUCT_STATUS);
/** Частые единицы; backend принимает и другие (из 1С). */
const UNITS = ['pcs', 'm', 'm2', 'kg', 'set', 'pack', 'l'];
const UNIT_NAMES: Record<string, string> = {
  pcs: 'штука',
  m: 'метр',
  m2: 'квадратный метр',
  kg: 'килограмм',
  set: 'комплект',
  pack: 'упаковка',
  l: 'литр',
};

/** Единица не из списка (пришла из 1С) остаётся выбранной, а не теряется. */
function unitOptions(current: string) {
  const units = current && !UNITS.includes(current) ? [...UNITS, current] : UNITS;
  return units.map((unit) => ({
    value: unit,
    label: UNIT_NAMES[unit] ? `${unitLabel(unit)} — ${UNIT_NAMES[unit]}` : unit,
  }));
}

type Props = {
  form: MainForm;
  errors: MainFormErrors;
  disabled?: boolean;
  /** Новый товар: slug идёт за названием, пока его не правили руками. */
  autoSlug?: boolean;
  onChange: (patch: Partial<MainForm>) => void;
};

export function MainFields({ form, errors, disabled = false, autoSlug = false, onChange }: Props) {
  return (
    <div className={styles.formGrid}>
      <Field label="Название" required error={errors.name} className={styles.wide}>
        <Input
          name="name"
          maxLength={500}
          value={form.name}
          disabled={disabled}
          onChange={(event) => {
            const name = event.target.value;
            // У существующего товара slug не трогаем: смена ломает ссылки.
            const follows = autoSlug && form.slug === slugFromName(form.name);
            onChange(follows ? { name, slug: slugFromName(name) } : { name });
          }}
        />
      </Field>

      <Field
        label="Артикул (SKU)"
        required
        error={errors.sku}
        hint="Латиница, цифры и . _ / -. Должен совпадать с учётной системой."
      >
        <Input
          name="sku"
          className="mono"
          maxLength={64}
          autoComplete="off"
          value={form.sku}
          disabled={disabled}
          onChange={(event) => onChange({ sku: event.target.value })}
        />
      </Field>

      <div className={styles.slugRow}>
        <Field
          label="Адрес страницы (slug)"
          required
          error={errors.slug}
          hint="Строчная латиница, цифры и дефис. Смена ломает старые ссылки."
        >
          <Input
            name="slug"
            className="mono"
            maxLength={200}
            autoComplete="off"
            value={form.slug}
            disabled={disabled}
            onChange={(event) => onChange({ slug: event.target.value })}
          />
        </Field>
        <Button
          size="sm"
          variant="ghost"
          className={styles.slugButton}
          disabled={disabled || !form.name.trim()}
          onClick={() => onChange({ slug: slugFromName(form.name) })}
          title="Транслитерация названия; проверьте результат перед сохранением"
        >
          Из названия
        </Button>
      </div>

      <Field label="Статус" error={errors.status}>
        <Select
          name="status"
          options={STATUS_OPTIONS}
          value={form.status}
          disabled={disabled}
          onChange={(event) => onChange({ status: event.target.value as MainForm['status'] })}
        />
      </Field>

      <Field label="Единица" required error={errors.unit} hint="Канаты и тросы — обычно метр.">
        <Select
          name="unit"
          options={unitOptions(form.unit)}
          value={form.unit}
          disabled={disabled}
          onChange={(event) => onChange({ unit: event.target.value })}
        />
      </Field>

      <Field label="Минимальная партия" required error={errors.minOrderQty}>
        <Input
          name="minOrderQty"
          inputMode="decimal"
          value={form.minOrderQty}
          disabled={disabled}
          onChange={(event) => onChange({ minOrderQty: event.target.value })}
        />
      </Field>

      <Field label="Бренд" error={errors.brand}>
        <Input
          name="brand"
          maxLength={255}
          value={form.brand}
          disabled={disabled}
          onChange={(event) => onChange({ brand: event.target.value })}
        />
      </Field>

      <Field
        label="Код во внешней системе (external_id)"
        error={errors.externalId}
        hint="Заполняется для сопоставления с 1С."
      >
        <Input
          name="externalId"
          className="mono"
          maxLength={64}
          value={form.externalId}
          disabled={disabled}
          onChange={(event) => onChange({ externalId: event.target.value })}
        />
      </Field>

      <Field label="Короткое описание" error={errors.shortDescription} className={styles.wide}>
        <Textarea
          name="shortDescription"
          rows={2}
          value={form.shortDescription}
          disabled={disabled}
          onChange={(event) => onChange({ shortDescription: event.target.value })}
        />
      </Field>

      <Field label="Описание" error={errors.description} className={styles.wide}>
        <Textarea
          name="description"
          rows={6}
          value={form.description}
          disabled={disabled}
          onChange={(event) => onChange({ description: event.target.value })}
        />
      </Field>

      <div className={`${styles.switches} ${styles.wide}`}>
        <Switch
          label="Активен"
          description="Неактивный товар скрыт с сайта, но остаётся в каталоге."
          checked={form.isActive}
          disabled={disabled}
          onChange={(event) => onChange({ isActive: event.target.checked })}
        />
        <Switch
          label="Избранный"
          description="Показывается в подборках на главной."
          checked={form.isFeatured}
          disabled={disabled}
          onChange={(event) => onChange({ isFeatured: event.target.checked })}
        />
      </div>
    </div>
  );
}
