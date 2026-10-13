import type { ProductListItem } from '@oinau/api-types';

import { ProductCardSkeleton } from '@/components/ui/States';
import { ProductCard } from './ProductCard';
import styles from './ProductGrid.module.css';

export function ProductGrid({ products }: { products: ProductListItem[] }) {
  return (
    <div className={styles.grid}>
      {products.map((product, index) => (
        <ProductCard key={product.sku} product={product} priority={index < 4} />
      ))}
    </div>
  );
}

/** Сетка-заглушка: показывается, пока грузится страница каталога. */
export function ProductGridSkeleton({ count = 8 }: { count?: number }) {
  return (
    <div className={styles.grid}>
      {Array.from({ length: count }, (_, index) => (
        <ProductCardSkeleton key={index} />
      ))}
    </div>
  );
}
