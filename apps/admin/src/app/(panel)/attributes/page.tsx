import type { Metadata } from 'next';
import { Suspense } from 'react';

import { AttributesScreen } from '@/components/attributes/AttributesScreen';
import { RequirePermission } from '@/components/session/AuthGate';
import { PageLoader } from '@/components/ui/States';
import { Permission } from '@/lib/auth/permissions';

export const metadata: Metadata = { title: 'Характеристики' };

export default function AttributesPage() {
  return (
    <RequirePermission all={[Permission.CATALOG_READ]}>
      <Suspense fallback={<PageLoader />}>
        <AttributesScreen />
      </Suspense>
    </RequirePermission>
  );
}
