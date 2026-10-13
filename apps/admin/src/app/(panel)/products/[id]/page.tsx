import type { Metadata } from 'next';
import { Suspense } from 'react';

import { ProductEditorScreen } from '@/components/products/ProductEditorScreen';
import { RequirePermission } from '@/components/session/AuthGate';
import { PageLoader } from '@/components/ui/States';
import { Permission } from '@/lib/auth/permissions';

export const metadata: Metadata = { title: 'Товар' };

export default async function ProductPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const numeric = /^\d+$/.test(id) ? Number(id) : Number.NaN;
  return (
    <RequirePermission all={[Permission.CATALOG_READ]}>
      {/* Активная вкладка читается из адреса (useSearchParams). */}
      <Suspense fallback={<PageLoader />}>
        <ProductEditorScreen id={numeric} />
      </Suspense>
    </RequirePermission>
  );
}
