'use client';

/**
 * Карточка характеристики в боковой панели: основные поля, варианты
 * значений (для OPTION), где используется, удаление.
 */

import { useMemo, useState, type FormEvent } from 'react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Dialog, useConfirm } from '@/components/ui/Dialog';
import { Field, Input, Select, Switch } from '@/components/ui/Field';
import { Icon } from '@/components/ui/Icon';
import { useToast } from '@/components/ui/Toast';
import { ApiError } from '@/lib/api/client';
import { attributesApi } from '@/lib/api/endpoints';
import type { AttributeRead, AttributeValueType } from '@/lib/api/types';
import {
  attributeErrorsFromApi,
  buildAttributeCreate,
  buildAttributeUpdate,
  EMPTY_ATTRIBUTE_FORM,
  formFromAttribute,
  newOptionDraft,
  optionDraftError,
  validateAttributeForm,
  VALUE_TYPE_META,
  type AttributeForm,
  type AttributeFormErrors,
  type OptionDraft,
} from '@/lib/attributeForm';
import { isForbidden } from '@/lib/errors';
import { formatCount, plural } from '@/lib/format';
import { slugFromName } from '@/lib/products';

import { OptionsManager } from './OptionsManager';
import styles from './Attributes.module.css';

const TYPE_OPTIONS = (Object.keys(VALUE_TYPE_META) as AttributeValueType[]).map((value) => ({
  value,
  label: VALUE_TYPE_META[value].label,
}));

type Props = {
  attribute: AttributeRead | null;
  canWrite: boolean;
  onClose: () => void;
  onChanged: (attribute: AttributeRead | null) => void;
  onDeleted: () => void;
  onOpenCategory: (id: number) => void;
};

export function AttributeDrawer({
  attribute,
  canWrite,
  onClose,
  onChanged,
  onDeleted,
  onOpenCategory,
}: Props) {
  const toast = useToast();
  const confirm = useConfirm();
  const creating = attribute === null;
  const [current, setCurrent] = useState<AttributeRead | null>(attribute);
  const initial = useMemo(
    () => (current ? formFromAttribute(current) : EMPTY_ATTRIBUTE_FORM),
    [current],
  );
  const [form, setForm] = useState<AttributeForm>(initial);
  const [errors, setErrors] = useState<AttributeFormErrors>({});
  const [drafts, setDrafts] = useState<OptionDraft[]>([]);
  const [draftErrors, setDraftErrors] = useState<Record<string, { value?: string; slug?: string }>>(
    {},
  );
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const set = (patch: Partial<AttributeForm>) => setForm((state) => ({ ...state, ...patch }));
  const dirty = creating || JSON.stringify(form) !== JSON.stringify(initial);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canWrite || saving) return;
    const local = validateAttributeForm(form, creating);
    const optionErrors: Record<string, { value?: string; slug?: string }> = {};
    if (creating && form.valueType === 'OPTION') {
      for (const draft of drafts) {
        const draftError = optionDraftError(draft);
        if (Object.keys(draftError).length > 0) optionErrors[draft.key] = draftError;
      }
    }
    setErrors(local);
    setDraftErrors(optionErrors);
    if (Object.keys(local).length > 0 || Object.keys(optionErrors).length > 0) return;
    setSaving(true);
    try {
      if (creating) {
        const created = await attributesApi.create(buildAttributeCreate(form, drafts));
        toast.success('Характеристика создана', created.name);
        setCurrent(created);
        setForm(formFromAttribute(created));
        setDrafts([]);
        onChanged(created);
      } else if (current) {
        const payload = buildAttributeUpdate(form, initial);
        if (Object.keys(payload).length === 0) return;
        const updated = await attributesApi.update(current.id, payload);
        setCurrent(updated);
        setForm(formFromAttribute(updated));
        toast.success('Изменения сохранены');
        onChanged(updated);
      }
    } catch (error) {
      setErrors(attributeErrorsFromApi(error));
      toast.error(isForbidden(error) ? 'Нет права изменять характеристики' : 'Не сохранено', error);
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!current) return;
    const categories = current.categories ?? [];
    const approved = await confirm({
      title: `Удалить характеристику «${current.name}»?`,
      description:
        categories.length > 0
          ? `Она назначена ${formatCount(categories.length)} ${plural(categories.length, ['категории', 'категориям', 'категориям'])} (${categories.map((item) => item.name).join(', ')}) и будет убрана из них. Удалить можно только характеристику без значений у товаров.`
          : 'Удалить можно только характеристику без значений у товаров. Действие необратимо.',
      confirmLabel: 'Удалить',
    });
    if (!approved) return;
    setDeleting(true);
    try {
      await attributesApi.remove(current.id);
      toast.success('Характеристика удалена', current.name);
      onDeleted();
    } catch (error) {
      toast.error(
        error instanceof ApiError && error.code === 'attribute_in_use'
          ? 'Характеристика используется в товарах — отключите её вместо удаления'
          : isForbidden(error)
            ? 'Нет права удалять характеристики'
            : 'Характеристика не удалена',
        error,
      );
    } finally {
      setDeleting(false);
    }
  };

  const disabled = !canWrite || saving;

  return (
    <Dialog
      open
      variant="drawer"
      size="lg"
      onClose={onClose}
      busy={saving || deleting}
      title={creating ? 'Новая характеристика' : current?.name}
      description={
        current ? (
          <span className={styles.drawerMeta}>
            <span className="mono">{current.code}</span> · у товаров:{' '}
            {formatCount(current.usage_count)}
          </span>
        ) : (
          'Код и тип значения задаются один раз и потом не меняются.'
        )
      }
    >
      <div className={styles.drawerBody}>
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
                disabled={disabled}
                onChange={(event) => set({ name: event.target.value })}
              />
            </Field>

            {creating ? (
              <>
                <Field
                  label="Код"
                  required
                  error={errors.code}
                  hint="Строчная латиница, цифры и _. Не меняется."
                >
                  <Input
                    name="code"
                    className="mono"
                    maxLength={64}
                    value={form.code}
                    disabled={disabled}
                    onChange={(event) => set({ code: event.target.value })}
                  />
                </Field>
                <Field
                  label="Тип значения"
                  required
                  error={errors.valueType}
                  hint={VALUE_TYPE_META[form.valueType].hint}
                >
                  <Select
                    name="valueType"
                    options={TYPE_OPTIONS}
                    value={form.valueType}
                    disabled={disabled}
                    onChange={(event) =>
                      set({ valueType: event.target.value as AttributeValueType })
                    }
                  />
                </Field>
              </>
            ) : (
              <div
                className={`${styles.readonlyFacts} ${styles.wide}`}
                data-testid="immutable-fields"
              >
                <div>
                  <span className={styles.muted}>Код</span>
                  <span className="mono">{form.code}</span>
                </div>
                <div>
                  <span className={styles.muted}>Тип значения</span>
                  <span className={styles.typeLine}>
                    <Badge tone="neutral">{VALUE_TYPE_META[form.valueType].label}</Badge>
                    <span className={styles.lockHint}>
                      <Icon name="lock" size={12} /> Не меняется: значения товаров хранятся в этом
                      типе
                    </span>
                  </span>
                </div>
              </div>
            )}

            <Field label="Единица измерения" error={errors.unit} hint="Например: мм, кг, м">
              <Input
                name="unit"
                maxLength={16}
                value={form.unit}
                disabled={disabled}
                onChange={(event) => set({ unit: event.target.value })}
              />
            </Field>
            <Field label="Порядок" error={errors.sortOrder}>
              <Input
                name="sortOrder"
                inputMode="numeric"
                value={form.sortOrder}
                disabled={disabled}
                onChange={(event) => set({ sortOrder: event.target.value })}
              />
            </Field>
            <div className={`${styles.switches} ${styles.wide}`}>
              <Switch
                label="Активна"
                description="Отключённая не показывается в фильтрах; значения товаров сохраняются."
                checked={form.isActive}
                disabled={disabled}
                onChange={(event) => set({ isActive: event.target.checked })}
              />
              <Switch
                label="Фильтр в каталоге"
                checked={form.isFilterable}
                disabled={disabled}
                onChange={(event) => set({ isFilterable: event.target.checked })}
              />
              <Switch
                label="Видна на сайте"
                checked={form.isVisible}
                disabled={disabled}
                onChange={(event) => set({ isVisible: event.target.checked })}
              />
            </div>
          </div>

          {creating && form.valueType === 'OPTION' ? (
            <div className={styles.draftOptions}>
              <p className={styles.subheading}>Варианты значений</p>
              {drafts.map((draft, index) => (
                <div key={draft.key} className={styles.optionRow}>
                  <Field label={`Вариант ${index + 1}`} error={draftErrors[draft.key]?.value}>
                    <Input
                      value={draft.value}
                      disabled={disabled}
                      onChange={(event) =>
                        setDrafts((list) =>
                          list.map((item) =>
                            item.key === draft.key
                              ? {
                                  ...item,
                                  value: event.target.value,
                                  // slug подставляется, пока его не правили вручную
                                  slug:
                                    item.slug === slugFromName(item.value)
                                      ? slugFromName(event.target.value)
                                      : item.slug,
                                }
                              : item,
                          ),
                        )
                      }
                    />
                  </Field>
                  <Field label="slug" error={draftErrors[draft.key]?.slug}>
                    <Input
                      className="mono"
                      value={draft.slug}
                      disabled={disabled}
                      onChange={(event) =>
                        setDrafts((list) =>
                          list.map((item) =>
                            item.key === draft.key ? { ...item, slug: event.target.value } : item,
                          ),
                        )
                      }
                    />
                  </Field>
                  <Button
                    size="sm"
                    variant="dangerGhost"
                    icon="close"
                    aria-label={`Убрать вариант ${index + 1}`}
                    onClick={() =>
                      setDrafts((list) => list.filter((item) => item.key !== draft.key))
                    }
                  />
                </div>
              ))}
              <Button
                size="sm"
                icon="plus"
                disabled={disabled}
                onClick={() => setDrafts((list) => [...list, newOptionDraft()])}
              >
                Добавить вариант
              </Button>
            </div>
          ) : null}

          {canWrite ? (
            <div className={styles.formActions}>
              <Button type="submit" variant="primary" loading={saving} disabled={!dirty}>
                {creating ? 'Создать' : 'Сохранить'}
              </Button>
            </div>
          ) : (
            <p className={styles.readOnly}>
              <Icon name="lock" size={14} /> Только просмотр: у вашей роли нет права изменять
              каталог.
            </p>
          )}
        </form>

        {current && current.value_type === 'OPTION' ? (
          <OptionsManager
            attribute={current}
            canWrite={canWrite}
            onChanged={(updated) => {
              setCurrent(updated);
              onChanged(updated);
            }}
          />
        ) : null}

        {current ? (
          <section className={styles.section} aria-labelledby="attribute-usage">
            <p id="attribute-usage" className={styles.subheading}>
              Где используется
            </p>
            {(current.categories ?? []).length === 0 ? (
              <p className={styles.muted}>Не назначена ни одной категории.</p>
            ) : (
              <ul className={styles.categoryChips}>
                {(current.categories ?? []).map((category) => (
                  <li key={category.id}>
                    <button
                      type="button"
                      className={styles.chip}
                      onClick={() => onOpenCategory(category.id)}
                    >
                      {category.name}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <p className={styles.muted}>
              Значений у товаров: {formatCount(current.usage_count)}.{' '}
              {current.usage_count > 0 ? 'Пока они есть, характеристику нельзя удалить.' : null}
            </p>
            {canWrite ? (
              <div>
                <Button
                  variant="dangerGhost"
                  icon="trash"
                  loading={deleting}
                  onClick={() => void remove()}
                >
                  Удалить характеристику
                </Button>
              </div>
            ) : null}
          </section>
        ) : null}
      </div>
    </Dialog>
  );
}
