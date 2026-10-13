import { ProductGridSkeleton } from '@/components/catalog/ProductGrid';
import { Skeleton } from '@/components/ui/States';

/** Каркас каталога на время загрузки выдачи с сервера. */
export default function CatalogLoading() {
  return (
    <div
      style={{
        maxWidth: 'var(--container)',
        margin: '0 auto',
        padding: 'var(--space-6) var(--gutter)',
      }}
    >
      <Skeleton height="40px" width="320px" />
      <div style={{ marginTop: 'var(--space-6)' }}>
        <ProductGridSkeleton count={8} />
      </div>
    </div>
  );
}
