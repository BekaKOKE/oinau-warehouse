'use client';

/**
 * Карточка товара.
 *
 * Разделы — отдельные вкладки со своим сохранением: у каждого домена свой
 * эндпоинт (товар, категории, характеристики, цены, изображения, остатки),
 * и одна гигантская форма смешала бы их ошибки и транзакции.
 *
 * Удалённый товар backend разрешает только читать и восстанавливать —
 * интерфейс показывает всё в режиме просмотра и не пытается обойти правило.
 */

import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';

import { RequirePermission } from '@/components/session/AuthGate';
import { useSession } from '@/components/session/SessionProvider';
import { Badge, EnumBadge } from '@/components/ui/Badge';
import { Button, ButtonLink } from '@/components/ui/Button';
import { useConfirm } from '@/components/ui/Dialog';
import { Icon } from '@/components/ui/Icon';
import { Card, PageHeader } from '@/components/ui/Layout';
import { EmptyState, ErrorState, PageLoader } from '@/components/ui/States';
import { useToast } from '@/components/ui/Toast';
import { ApiError } from '@/lib/api/client';
import { productsApi } from '@/lib/api/endpoints';
import type { ProductRead } from '@/lib/api/types';
import { Permission } from '@/lib/auth/permissions';
import { SITE_URL } from '@/lib/config';
import { isNotFound } from '@/lib/errors';
import { formatDateTime } from '@/lib/format';
import { useQuery } from '@/lib/hooks/useQuery';
import { useUnsavedGuard } from '@/lib/hooks/useUnsavedGuard';
import { PRODUCT_STATUS } from '@/lib/labels';
import { productSiteUrl } from '@/lib/products';

import { AttributesSection } from './sections/AttributesSection';
import { CategoriesSection } from './sections/CategoriesSection';
import { ColorsSection } from './sections/ColorsSection';
import { ImagesSection } from './sections/ImagesSection';
import { MainSection } from './sections/MainSection';
import { PricingSection } from './sections/PricingSection';
import { StockSection } from './sections/StockSection';
import styles from './ProductEditor.module.css';

export const PRODUCT_TABS = [
  { id: 'main', label: 'Основное' },
  { id: 'categories', label: 'Категории' },
  { id: 'attributes', label: 'Характеристики' },
  { id: 'pricing', label: 'Цены' },
  { id: 'images', label: 'Изображения' },
  { id: 'stock', label: 'Наличие' },
  { id: 'colors', label: 'Цвета' },
] as const;

export type ProductTab = (typeof PRODUCT_TABS)[number]['id'];

function isTab(value: string | null): value is ProductTab {
  return PRODUCT_TABS.some((tab) => tab.id === value);
}

const BREADCRUMBS = [{ label: 'Товары', href: '/products' }];

export type SectionProps = {
  product: ProductRead;
  /** Право на изменение каталога и товар не удалён. */
  canWrite: boolean;
  onProductChange: (product: ProductRead) => void;
  onDirtyChange: (dirty: boolean) => void;
};

function NotFound() {
  return (
    <>
      <PageHeader title="Товар не найден" breadcrumbs={BREADCRUMBS} />
      <Card>
        <EmptyState
          icon="products"
          title="Такого товара нет"
          description="Возможно, ссылка устарела."
          action={
            <ButtonLink href="/products" icon="chevronLeft">
              К списку товаров
            </ButtonLink>
          }
        />
      </Card>
    </>
  );
}

/**
 * Данные запрашиваются только внутри `RequirePermission`: роли без
 * права не нужен ни запрос, ни гарантированный 403.
 */
export function ProductEditorScreen({ id }: { id: number }) {
  return (
    <RequirePermission all={[Permission.CATALOG_READ]}>
      <ProductEditorPanel id={id} />
    </RequirePermission>
  );
}

function ProductEditorPanel({ id }: { id: number }) {
  const { can } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const confirm = useConfirm();
  const toast = useToast();

  const valid = Number.isInteger(id) && id > 0;
  const query = useQuery((signal) => productsApi.get(id, { signal }), [id], { enabled: valid });
  const tabParam = searchParams.get('tab');
  const [tab, setTab] = useState<ProductTab>(isTab(tabParam) ? tabParam : 'main');
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState<'delete' | 'restore' | null>(null);

  useUnsavedGuard(dirty);

  // На узком экране вкладки прокручиваются: активная не должна прятаться за краем.
  useEffect(() => {
    document
      .getElementById(`tab-${tab}`)
      ?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
  }, [tab, query.status]);
  const onDirtyChange = useCallback((value: boolean) => setDirty(value), []);

  const switchTab = async (next: ProductTab) => {
    if (next === tab) return;
    if (dirty) {
      const leave = await confirm({
        title: 'Уйти без сохранения?',
        description: 'В разделе есть несохранённые изменения. Они будут потеряны.',
        confirmLabel: 'Не сохранять',
      });
      if (!leave) return;
    }
    setDirty(false);
    setTab(next);
    router.replace(`${pathname}${next === 'main' ? '' : `?tab=${next}`}`, { scroll: false });
  };

  if (!valid) return <NotFound />;
  if (query.status === 'error' && isNotFound(query.error)) return <NotFound />;
  if (query.status === 'error' && !query.data) {
    return (
      <>
        <PageHeader title="Товар" breadcrumbs={BREADCRUMBS} />
        <Card>
          <ErrorState error={query.error} onRetry={query.reload} />
        </Card>
      </>
    );
  }
  if (!query.data) return <PageLoader label="Загружаем товар…" />;

  const product = query.data;
  const deleted = Boolean(product.deleted_at);
  const catalogWrite = can(Permission.CATALOG_WRITE);
  const canWrite = catalogWrite && !deleted;

  const remove = async () => {
    const approved = await confirm({
      title: `Удалить товар «${product.name}»?`,
      description:
        'Товар пропадёт с сайта и из поиска, его нельзя будет добавить в заявку. Заявки, где он уже есть, не изменятся. Товар можно будет восстановить.',
      confirmLabel: 'Удалить',
    });
    if (!approved) return;
    setBusy('delete');
    try {
      await productsApi.remove(product.id);
      setDirty(false);
      toast.success('Товар удалён', product.sku);
      query.reload();
    } catch (error) {
      toast.error(
        error instanceof ApiError && error.status === 403
          ? 'Нет права удалять товары'
          : 'Товар не удалён',
        error,
      );
      if (isNotFound(error)) query.reload();
    } finally {
      setBusy(null);
    }
  };

  const restore = async () => {
    setBusy('restore');
    try {
      const restored = await productsApi.restore(product.id);
      query.setData(restored);
      toast.success(
        'Товар восстановлен',
        restored.is_active ? undefined : 'Он неактивен: включите «Активен», чтобы вернуть на сайт.',
      );
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        toast.error(
          'Восстановить нельзя',
          new ApiError(
            409,
            error.code,
            `${error.message}. Измените артикул или slug у товара, который его занял.`,
          ),
        );
      } else {
        toast.error(
          error instanceof ApiError && error.status === 403
            ? 'Нет права восстанавливать товары'
            : 'Товар не восстановлен',
          error,
        );
      }
    } finally {
      setBusy(null);
    }
  };

  const sectionProps: SectionProps = {
    product,
    canWrite,
    onProductChange: query.setData,
    onDirtyChange,
  };

  return (
    <>
      <PageHeader
        breadcrumbs={[...BREADCRUMBS, { label: product.sku }]}
        title={product.name}
        meta={
          <>
            <span className={`mono ${styles.muted}`}>{product.sku}</span>
            <EnumBadge value={product.status} meta={PRODUCT_STATUS} />
            {deleted ? (
              <Badge tone="danger">Удалён</Badge>
            ) : product.is_active ? (
              <Badge tone="success">Активен</Badge>
            ) : (
              <Badge tone="neutral">Неактивен</Badge>
            )}
            {product.is_featured ? <Badge tone="accent">Избранный</Badge> : null}
            {product.is_publicly_visible ? (
              <Badge tone="info">На сайте</Badge>
            ) : (
              <Badge tone="warning" title="Товар должен быть опубликован, активен и не удалён">
                Не виден на сайте
              </Badge>
            )}
          </>
        }
        actions={
          <>
            {product.is_publicly_visible ? (
              <a
                className={styles.siteLink}
                href={productSiteUrl(SITE_URL, product.slug)}
                target="_blank"
                rel="noreferrer"
              >
                <Icon name="external" size={14} /> На сайте
              </a>
            ) : null}
            {catalogWrite && !deleted ? (
              <Button
                variant="dangerGhost"
                icon="trash"
                loading={busy === 'delete'}
                onClick={() => void remove()}
              >
                Удалить
              </Button>
            ) : null}
          </>
        }
      />

      {deleted ? (
        <div className={styles.deletedBanner} role="status">
          <Icon name="alert" size={18} />
          <div>
            <p className={styles.strong}>Товар удалён {formatDateTime(product.deleted_at)}</p>
            <p className={styles.muted}>
              Удалённый товар доступен только для просмотра. Восстановление вернёт карточку, но не
              включит товар обратно — активность задаётся отдельно.
            </p>
          </div>
          {catalogWrite ? (
            <Button
              variant="primary"
              icon="refresh"
              loading={busy === 'restore'}
              onClick={() => void restore()}
            >
              Восстановить
            </Button>
          ) : null}
        </div>
      ) : !catalogWrite ? (
        <p className={styles.readOnlyNote}>
          <Icon name="lock" size={14} /> Только просмотр: у вашей роли нет права изменять каталог.
        </p>
      ) : null}

      <div className={styles.tabs} role="tablist" aria-label="Разделы товара">
        {PRODUCT_TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            id={`tab-${item.id}`}
            aria-selected={tab === item.id}
            aria-controls={`panel-${item.id}`}
            className={`${styles.tab} ${tab === item.id ? styles.tabActive : ''}`}
            onClick={() => void switchTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div
        role="tabpanel"
        id={`panel-${tab}`}
        aria-labelledby={`tab-${tab}`}
        className={styles.panel}
      >
        {tab === 'main' ? (
          <MainSection key={`main-${product.updated_at}`} {...sectionProps} />
        ) : null}
        {tab === 'categories' ? <CategoriesSection {...sectionProps} /> : null}
        {tab === 'attributes' ? <AttributesSection {...sectionProps} /> : null}
        {tab === 'pricing' ? <PricingSection {...sectionProps} /> : null}
        {tab === 'images' ? <ImagesSection {...sectionProps} /> : null}
        {tab === 'stock' ? <StockSection {...sectionProps} /> : null}
        {tab === 'colors' ? <ColorsSection {...sectionProps} /> : null}
      </div>
    </>
  );
}
