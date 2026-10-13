import type { Metadata } from 'next';
import { Suspense } from 'react';

import { ProductsList } from '@/components/products/ProductsList';
import { RequirePermission } from '@/components/session/AuthGate';
import { PageLoader } from '@/components/ui/States';
import { Permission } from '@/lib/auth/permissions';

export const metadata: Metadata = { title: 'Товары' };

export default function ProductsPage() {
  return (
    <RequirePermission all={[Permission.CATALOG_READ]}>
      <Suspense fallback={<PageLoader />}>
        <ProductsList />
      </Suspense>
    </RequirePermission>
  );
}
