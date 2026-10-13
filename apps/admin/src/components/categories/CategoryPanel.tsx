'use client';

/**
 * Карточка категории: основные поля, удаление и восстановление,
 * характеристики категории.
 *
 * Правила backend не дублируются, а объясняются: удалить нельзя категорию
 * с живыми подкатегориями или с товарами, восстановить — при занятом slug
 * или удалённом родителе. Кнопки показываются, а решение и текст ошибки
 * приходят с сервера.
 */

import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';

import { MediaLibraryDialog } from '@/components/content/MediaLibraryDialog';
import { useSession } from '@/components/session/SessionProvider';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { useConfirm } from '@/components/ui/Dialog';
import { Field, Input, Select, Switch, Textarea } from '@/components/ui/Field';
import { Icon } from '@/components/ui/Icon';
import { Card } from '@/components/ui/Layout';
import { ErrorState, Skeleton } from '@/components/ui/States';
import { useToast } from '@/components/ui/Toast';
import { ApiError } from '@/lib/api/client';
import { categoriesApi } from '@/lib/api/endpoints';
import type { CategoryRead, CategoryTreeNode } from '@/lib/api/types';
import { Permission } from '@/lib/auth/permissions';
import {
  buildCategoryCreate,
  buildCategoryUpdate,
  categoryErrorsFromApi,
  emptyCategoryForm,
  formFromCategory,
  indexTree,
  isCategoryFormDirty,
  liveChildren,
  parentOptions,
  pathOf,
  subtreeIds,
  validateCategoryForm,
  type CategoryForm,
  type CategoryFormErrors,
} from '@/lib/categories';
import { describeError, isForbidden, isNotFound } from '@/lib/errors';
import { formatCount, formatDateTime, plural } from '@/lib/format';
import { useQuery } from '@/lib/hooks/useQuery';
import { useUnsavedGuard } from '@/lib/hooks/useUnsavedGuard';
import { failureText, IMAGE_ACCEPT, StorageUploadError, uploadMediaFile } from '@/lib/media';
import { slugFromName } from '@/lib/products';

import { CategoryAttributesEditor } from './CategoryAttributesEditor';
import styles from './Categories.module.css';

type Props = {
  categoryId: number | null;
  defaultParentId: number | null;
  tree: readonly CategoryTreeNode[];
  canWrite: boolean;
  onClose: () => void;
  onSaved: (id: number) => void;
  onTreeChanged: () => void;
  onAddChild: (parentId: number) => void;
};

export function CategoryPanel(props: Props) {
  const { categoryId } = props;
  const query = useQuery((signal) => categoriesApi.get(categoryId ?? 0, { signal }), [categoryId], {
    enabled: categoryId !== null,
  });

  if (categoryId === null)
    return <CategoryEditor {...props} category={null} onReload={() => undefined} />;
  if (query.status === 'error' && !query.data) {
    return (
      <Card title="Категория">
        {isNotFound(query.error) ? (
          <p className={styles.muted}>Категория не найдена — возможно, ссылка устарела.</p>
        ) : (
          <ErrorState error={query.error} onRetry={query.reload} compact />
        )}
        <Button variant="ghost" icon="chevronLeft" onClick={props.onClose}>
          К дереву
        </Button>
      </Card>
    );
  }
  if (!query.data) {
    return (
      <Card title="Категория">
        <div className={styles.stack} aria-busy="true">
          <Skeleton height={36} />
          <Skeleton height={36} />
          <Skeleton height={90} />
        </div>
      </Card>
    );
  }
  return (
    <CategoryEditor
      key={query.data.updated_at + (query.data.deleted_at ?? '')}
      {...props}
      category={query.data}
      onReload={query.reload}
      onReplace={query.setData}
    />
  );
}

function CategoryEditor({
  category,
  defaultParentId,
  tree,
  canWrite,
  onClose,
  onSaved,
  onTreeChanged,
  onAddChild,
  onReload,
  onReplace,
}: Props & {
  category: CategoryRead | null;
  onReload: () => void;
  onReplace?: (category: CategoryRead) => void;
}) {
  const toast = useToast();
  const confirm = useConfirm();
  const creating = category === null;
  const deleted = Boolean(category?.deleted_at);
  const editable = canWrite && !deleted;

  const initial = useMemo(
    () => (category ? formFromCategory(category) : emptyCategoryForm(defaultParentId)),
    [category, defaultParentId],
  );
  const [form, setForm] = useState<CategoryForm>(initial);
  const [pickingImage, setPickingImage] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const { can } = useSession();
  const canUpload = can(Permission.CATALOG_WRITE, Permission.MEDIA_UPLOAD);
  const [errors, setErrors] = useState<CategoryFormErrors>({});
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState<'delete' | 'restore' | null>(null);

  const index = useMemo(() => indexTree(tree), [tree]);
  const node = category ? index.byId.get(category.id) : undefined;
  const exclude = useMemo(() => (node ? subtreeIds(node) : new Set<number>()), [node]);
  const parents = useMemo(() => parentOptions(tree, exclude), [tree, exclude]);
  const dirty = isCategoryFormDirty(form, initial);
  useUnsavedGuard(dirty && !saving);

  useEffect(() => setErrors({}), [category?.id]);

  const set = (patch: Partial<CategoryForm>) => setForm((current) => ({ ...current, ...patch }));

  // Тот же поток, что у разделов CMS: intent → PUT в хранилище → complete.
  // Варианты воркер строит после complete, поэтому превью может появиться
  // только после сохранения — ссылка на файл (UUID) уже есть.
  const onImageFile = async (file: File) => {
    setUploading(true);
    setUploadError(null);
    try {
      const media = await uploadMediaFile(file, 'CONTENT', { onStage: () => undefined });
      set({ imageUuid: media.uuid, imageUrl: media.variants?.thumb ?? media.url ?? '' });
    } catch (error) {
      setUploadError(
        error instanceof StorageUploadError
          ? error.message
          : error instanceof ApiError && error.code === 'upload_rejected'
            ? failureText(
                typeof error.details?.failure_reason === 'string'
                  ? error.details.failure_reason
                  : null,
              )
            : describeError(error),
      );
    } finally {
      setUploading(false);
    }
  };

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editable || saving) return;
    const local = validateCategoryForm(form);
    setErrors(local);
    if (Object.keys(local).length > 0) return;
    if (!creating && form.parentId !== initial.parentId && node && liveChildren(node).length > 0) {
      const approved = await confirm({
        title: 'Перенести ветку?',
        description:
          'Категория переедет вместе со всеми подкатегориями. Адреса разделов на сайте не изменятся, но изменятся хлебные крошки.',
        confirmLabel: 'Перенести',
        tone: 'primary',
      });
      if (!approved) return;
    }
    setSaving(true);
    try {
      if (creating) {
        const created = await categoriesApi.create(buildCategoryCreate(form));
        toast.success('Категория создана', created.name);
        onSaved(created.id);
      } else {
        const payload = buildCategoryUpdate(form, initial);
        if (Object.keys(payload).length === 0) return;
        const updated = await categoriesApi.update(category.id, payload);
        onReplace?.(updated);
        onTreeChanged();
        toast.success('Изменения сохранены');
      }
    } catch (error) {
      setErrors(categoryErrorsFromApi(error));
      toast.error(
        isForbidden(error)
          ? 'Нет права изменять категории'
          : creating
            ? 'Категория не создана'
            : 'Не сохранено',
        error,
      );
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!category) return;
    const approved = await confirm({
      title: `Удалить категорию «${category.name}»?`,
      description:
        'Категория исчезнет с сайта. Удалить можно только раздел без подкатегорий и без товаров; удалённую категорию можно восстановить.',
      confirmLabel: 'Удалить',
    });
    if (!approved) return;
    setBusy('delete');
    try {
      await categoriesApi.remove(category.id);
      toast.success('Категория удалена', category.name);
      onTreeChanged();
      onReload();
    } catch (error) {
      const title =
        error instanceof ApiError && error.code === 'category_has_children'
          ? 'Сначала удалите или перенесите подкатегории'
          : error instanceof ApiError && error.code === 'category_has_products'
            ? 'В категории есть товары — перенесите их в другой раздел'
            : isForbidden(error)
              ? 'Нет права удалять категории'
              : 'Категория не удалена';
      toast.error(title, error);
      if (isNotFound(error)) onReload();
    } finally {
      setBusy(null);
    }
  };

  const restore = async () => {
    if (!category) return;
    setBusy('restore');
    try {
      const restored = await categoriesApi.restore(category.id);
      onReplace?.(restored);
      onTreeChanged();
      toast.success(
        'Категория восстановлена',
        restored.is_active ? undefined : 'Она скрыта: включите «Активна», чтобы показать на сайте.',
      );
    } catch (error) {
      const title =
        error instanceof ApiError && error.code === 'slug_exists'
          ? 'Slug уже занят другой категорией — восстановление невозможно'
          : error instanceof ApiError && error.code === 'parent_deleted'
            ? 'Родительская категория удалена — сначала восстановите её'
            : isForbidden(error)
              ? 'Нет права восстанавливать категории'
              : 'Категория не восстановлена';
      toast.error(title, error);
    } finally {
      setBusy(null);
    }
  };

  const children = node ? liveChildren(node).length : 0;

  return (
    <div className={styles.stack}>
      <form onSubmit={onSubmit} noValidate>
        <Card
          title={creating ? 'Новая категория' : category.name}
          description={
            creating
              ? form.parentId
                ? `Внутри «${pathOf(index, Number(form.parentId))}»`
                : 'Корневой раздел каталога'
              : pathOf(index, category.id) || undefined
          }
          actions={
            <Button
              size="sm"
              variant="ghost"
              icon="close"
              aria-label="Закрыть карточку"
              onClick={onClose}
            />
          }
        >
          {category ? (
            <div className={styles.facts}>
              {deleted ? (
                <Badge tone="danger">Удалена {formatDateTime(category.deleted_at)}</Badge>
              ) : category.is_active ? (
                <Badge tone="success">Активна</Badge>
              ) : (
                <Badge tone="warning">Скрыта</Badge>
              )}
              <span className={styles.muted}>
                {formatCount(category.products_count)}{' '}
                {plural(category.products_count, ['товар', 'товара', 'товаров'])}
              </span>
              <span className={styles.muted}>
                {formatCount(children)}{' '}
                {plural(children, ['подкатегория', 'подкатегории', 'подкатегорий'])}
              </span>
            </div>
          ) : null}

          {deleted ? (
            <div className={styles.deletedNote} role="status">
              <Icon name="alert" size={16} />
              <span>
                Удалённая категория доступна только для просмотра. Восстановление проверит, свободен
                ли slug и не удалён ли родитель.
              </span>
              {canWrite ? (
                <Button
                  size="sm"
                  variant="primary"
                  icon="refresh"
                  loading={busy === 'restore'}
                  onClick={() => void restore()}
                >
                  Восстановить
                </Button>
              ) : null}
            </div>
          ) : null}

          {errors._form ? (
            <div className={styles.formAlert} role="alert">
              {errors._form}
            </div>
          ) : null}

          <div className={styles.formGrid}>
            <Field label="Название" required error={errors.name} className={styles.wide}>
              <Input
                name="name"
                maxLength={500}
                value={form.name}
                disabled={!editable || saving}
                onChange={(event) => {
                  const name = event.target.value;
                  // У новой категории slug идёт за названием, пока его не
                  // правили руками. У существующей не трогаем: смена slug
                  // меняет адрес раздела на сайте.
                  const follows = creating && form.slug === slugFromName(form.name);
                  set(follows ? { name, slug: slugFromName(name) } : { name });
                }}
              />
            </Field>
            <div className={styles.slugRow}>
              <Field
                label="Slug"
                required
                error={errors.slug}
                hint="Строчная латиница, цифры и дефис"
              >
                <Input
                  name="slug"
                  className="mono"
                  maxLength={200}
                  value={form.slug}
                  disabled={!editable || saving}
                  onChange={(event) => set({ slug: event.target.value })}
                />
              </Field>
              {editable ? (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={!form.name.trim() || saving}
                  onClick={() => set({ slug: slugFromName(form.name) })}
                >
                  Из названия
                </Button>
              ) : null}
            </div>
            <Field label="Родительская категория" error={errors.parentId}>
              <Select
                name="parentId"
                options={parents}
                placeholder="— Корневая —"
                value={form.parentId}
                disabled={!editable || saving}
                onChange={(event) => set({ parentId: event.target.value })}
              />
            </Field>
            <Field label="Порядок" error={errors.sortOrder} hint="Меньше — выше в списке">
              <Input
                name="sortOrder"
                inputMode="numeric"
                value={form.sortOrder}
                disabled={!editable || saving}
                onChange={(event) => set({ sortOrder: event.target.value })}
              />
            </Field>
            <Field label="Код во внешней системе" error={errors.externalId}>
              <Input
                name="externalId"
                className="mono"
                maxLength={64}
                value={form.externalId}
                disabled={!editable || saving}
                onChange={(event) => set({ externalId: event.target.value })}
              />
            </Field>
            <div className={styles.wide}>
              <span className={styles.imageLabel}>Изображение</span>
              <p className={styles.imageHint}>
                Обложка раздела на сайте: загрузите файл или выберите из медиатеки — той же, что у
                товаров. Без обложки витрина показывает фото товара из этого раздела.
              </p>
              <div className={styles.imageRow}>
                <span className={styles.imageThumb}>
                  {form.imageUrl ? (
                    // Миниатюра из медиатеки: оптимизатор Next здесь не нужен.
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={form.imageUrl} alt="" />
                  ) : (
                    <span className={styles.imageEmpty}>{form.imageUuid ? 'файл' : 'нет'}</span>
                  )}
                </span>
                {editable ? (
                  <div className={styles.imageActions}>
                    {canUpload ? (
                      <Button
                        size="sm"
                        icon="import"
                        loading={uploading}
                        disabled={saving}
                        onClick={() => fileRef.current?.click()}
                      >
                        Загрузить
                      </Button>
                    ) : null}
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={saving || uploading}
                      onClick={() => setPickingImage(true)}
                    >
                      {form.imageUuid ? 'Заменить из медиатеки' : 'Выбрать из медиатеки'}
                    </Button>
                    {form.imageUuid ? (
                      <Button
                        size="sm"
                        variant="dangerGhost"
                        disabled={saving || uploading}
                        onClick={() => set({ imageUuid: '', imageUrl: '' })}
                      >
                        Убрать
                      </Button>
                    ) : null}
                    <input
                      ref={fileRef}
                      type="file"
                      accept={IMAGE_ACCEPT}
                      className="visually-hidden"
                      tabIndex={-1}
                      aria-label="Файл обложки"
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        event.target.value = '';
                        if (file) void onImageFile(file);
                      }}
                    />
                  </div>
                ) : null}
              </div>
              {uploadError ? (
                <p className={styles.imageError} role="alert">
                  {uploadError}
                </p>
              ) : form.imageUuid && !form.imageUrl ? (
                <p className={styles.imageHint}>
                  Файл загружен и обрабатывается — превью появится после сохранения.
                </p>
              ) : null}
            </div>
            <Field label="Описание" error={errors.description} className={styles.wide}>
              <Textarea
                rows={3}
                value={form.description}
                disabled={!editable || saving}
                onChange={(event) => set({ description: event.target.value })}
              />
            </Field>
            <Field
              label="SEO-заголовок"
              error={errors.seoTitle}
              hint="Пусто — на сайте будет название категории"
            >
              <Input
                maxLength={500}
                placeholder={form.name.trim()}
                value={form.seoTitle}
                disabled={!editable || saving}
                onChange={(event) => set({ seoTitle: event.target.value })}
              />
            </Field>
            <Field
              label="SEO-описание"
              error={errors.seoDescription}
              hint="Пусто — на сайте будет описание категории"
            >
              <Input
                placeholder={form.description.trim()}
                value={form.seoDescription}
                disabled={!editable || saving}
                onChange={(event) => set({ seoDescription: event.target.value })}
              />
            </Field>
            <div className={styles.wide}>
              <Switch
                label="Активна"
                description="Скрытая категория не показывается на сайте, товары в ней остаются."
                checked={form.isActive}
                disabled={!editable || saving}
                onChange={(event) => set({ isActive: event.target.checked })}
              />
            </div>
          </div>

          {editable ? (
            <div className={styles.actions}>
              <div className={styles.actionsLeft}>
                {!creating ? (
                  <>
                    <Button
                      variant="dangerGhost"
                      icon="trash"
                      loading={busy === 'delete'}
                      onClick={() => void remove()}
                    >
                      Удалить
                    </Button>
                    <Button variant="ghost" icon="plus" onClick={() => onAddChild(category.id)}>
                      Подкатегория
                    </Button>
                  </>
                ) : null}
              </div>
              <div className={styles.actionsRight}>
                <Button
                  variant="ghost"
                  disabled={saving || (!dirty && !creating)}
                  onClick={() => (creating ? onClose() : setForm(initial))}
                >
                  {creating ? 'Отмена' : 'Отменить'}
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  loading={saving}
                  disabled={!creating && !dirty}
                >
                  {creating ? 'Создать' : 'Сохранить'}
                </Button>
              </div>
            </div>
          ) : !canWrite ? (
            <p className={styles.readOnly}>
              <Icon name="lock" size={14} /> Только просмотр: у вашей роли нет права изменять
              каталог.
            </p>
          ) : null}
        </Card>
      </form>

      <MediaLibraryDialog
        open={pickingImage}
        onClose={() => setPickingImage(false)}
        onSelect={(media) => {
          set({ imageUuid: media.uuid, imageUrl: media.variants?.thumb ?? media.url ?? '' });
          setPickingImage(false);
        }}
      />

      {category ? (
        <CategoryAttributesEditor categoryId={category.id} canWrite={editable} />
      ) : (
        <Card title="Характеристики категории">
          <p className={styles.muted}>Характеристики назначаются после создания категории.</p>
        </Card>
      )}
    </div>
  );
}
