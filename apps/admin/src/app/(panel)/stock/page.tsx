import type { Metadata } from 'next';
import { Suspense } from 'react';

import { RequirePermission } from '@/components/session/AuthGate';
import { StockScreen } from '@/components/stock/StockScreen';
import { PageLoader } from '@/components/ui/States';
import { Permission } from '@/lib/auth/permissions';

export const metadata: Metadata = { title: 'Склад' };

export default function StockPage() {
  return (
    <RequirePermission all={[Permission.CATALOG_READ]}>
      <Suspense fallback={<PageLoader />}>
        <StockScreen />
      </Suspense>
    </RequirePermission>
  );
}
