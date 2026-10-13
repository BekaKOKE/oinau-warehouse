'use client';

/**
 * Создание товара.
 *
 * Категории и характеристики передаются сразу в POST /products — backend
 * создаёт всё одной транзакцией, и товар не висит без категории. Цены,
 * изображения и остатки задаются уже в карточке: у них свои эндпоинты,
 * которым нужен id товара.
 */

import { useRouter } from 'next/navigation';
import { useMemo, useState, type FormEvent } from 'react';

import { RequirePermission } from '@/components/session/AuthGate';
import { Button, ButtonLink } from '@/components/ui/Button';
import { Card, PageHeader } from '@/components/ui/Layout';
import { useToast } from '@/components/ui/Toast';
import { Permission } from '@/lib/auth/permissions';
import { categoriesApi, productsApi } from '@/lib/api/endpoints';
import type { ProductCategoryItem } from '@/lib/api/types';
import { buildAttributeItems, type AttributeValues } from '@/lib/attributes';
import { useQuery } from '@/lib/hooks/useQuery';
import { useUnsavedGuard } from '@/lib/hooks/useUnsavedGuard';
import {
  buildCreatePayload,
  EMPTY_MAIN_FORM,
  isFormDirty,
  mainFormErrorsFromApi,
  validateMainForm,
  type MainForm,
  type MainFormErrors,
} from '@/lib/productForm';
import { flattenCategoryTree } from '@/lib/products';

import { AttributeEditor, useAttributeDefs } from './AttributeEditor';
import { CategoryPicker } from './CategoryPicker';
import { MainFields } from './MainFields';
import styles from './ProductEditor.module.css';

/**
 * Данные запрашиваются только внутри `RequirePermission`: роли без
 * права не нужен ни запрос, ни гарантированный 403.
 */
export function ProductCreateScreen() {
  return (
    <RequirePermission all={[Permission.CATALOG_WRITE]}>
      <ProductCreatePanel />
    </RequirePermission>
  );
}

function ProductCreatePanel() {
  const router = useRouter();
  const toast = useToast();
  const [form, setForm] = useState<MainForm>(EMPTY_MAIN_FORM);
  const [errors, setErrors] = useState<MainFormErrors>({});
  const [categories, setCategories] = useState<ProductCategoryItem[]>([]);
  const [values, setValues] = useState<AttributeValues>({});
  const [attributeErrors, setAttributeErrors] = useState<Record<number, string>>({});
  const [saving, setSaving] = useState(false);

  const tree = useQuery((signal) => categoriesApi.tree({ signal }), []);
  const flat = useMemo(() => flattenCategoryTree(tree.data ?? []), [tree.data]);
  const categoryIds = categories.map((item) => item.category_id);
  const defs = useAttributeDefs(categoryIds, []);

  const dirty =
    isFormDirty(form, EMPTY_MAIN_FORM) || categories.length > 0 || Object.keys(values).length > 0;
  useUnsavedGuard(dirty && !saving);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (saving) return;
    const localErrors = validateMainForm(form);
    const attributes = buildAttributeItems(defs.data ?? [], values);
    setErrors(localErrors);
    setAttributeErrors(attributes.ok ? {} : attributes.errors);
    if (Object.keys(localErrors).length > 0 || !attributes.ok) {
      toast.error('Проверьте поля формы');
      return;
    }
    setSaving(true);
    try {
      const created = await productsApi.create(
        buildCreatePayload(form, { categories, attributes: attributes.items }),
      );
      toast.success('Товар создан', `${created.sku} — задайте цену, фото и наличие`);
      router.push(`/products/${created.id}`);
    } catch (error) {
      setErrors(mainFormErrorsFromApi(error));
      toast.error('Товар не создан', error);
      setSaving(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Новый товар"
        breadcrumbs={[{ label: 'Товары', href: '/products' }, { label: 'Новый товар' }]}
        description="Цены, изображения и наличие настраиваются в карточке после создания."
      />
      <form className={styles.createForm} onSubmit={onSubmit} noValidate>
        {errors._form ? (
          <div className={styles.formAlert} role="alert">
            {errors._form}
          </div>
        ) : null}
        <Card title="Основное">
          <MainFields
            form={form}
            errors={errors}
            disabled={saving}
            autoSlug
            onChange={(patch) => setForm((current) => ({ ...current, ...patch }))}
          />
        </Card>
        <Card title="Категории">
          <CategoryPicker
            value={categories}
            categories={flat}
            loading={tree.status === 'loading'}
            disabled={saving}
            onChange={setCategories}
          />
        </Card>
        <Card title="Характеристики" description="Набор зависит от выбранных категорий.">
          <AttributeEditor
            defs={defs.data}
            loading={defs.status === 'loading'}
            error={defs.status === 'error' ? defs.error : undefined}
            onRetry={defs.reload}
            values={values}
            errors={attributeErrors}
            disabled={saving}
            onChange={(id, value) => setValues((current) => ({ ...current, [id]: value }))}
          />
        </Card>
        <div className={styles.stickyActions}>
          <ButtonLink href="/products" variant="ghost">
            Отмена
          </ButtonLink>
          <Button type="submit" variant="primary" loading={saving}>
            Создать товар
          </Button>
        </div>
      </form>
    </>
  );
}
