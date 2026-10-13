import type { Metadata } from 'next';
import { Suspense } from 'react';

import { ColorsScreen } from '@/components/colors/ColorsScreen';
import { RequirePermission } from '@/components/session/AuthGate';
import { PageLoader } from '@/components/ui/States';
import { Permission } from '@/lib/auth/permissions';

export const metadata: Metadata = { title: 'Цвета' };

export default function ColorsPage() {
  return (
    <RequirePermission all={[Permission.CATALOG_READ]}>
      <Suspense fallback={<PageLoader />}>
        <ColorsScreen />
      </Suspense>
    </RequirePermission>
  );
}
