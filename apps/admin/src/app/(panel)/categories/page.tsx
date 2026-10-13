import type { Metadata } from 'next';
import { Suspense } from 'react';

import { CategoriesScreen } from '@/components/categories/CategoriesScreen';
import { RequirePermission } from '@/components/session/AuthGate';
import { PageLoader } from '@/components/ui/States';
import { Permission } from '@/lib/auth/permissions';

export const metadata: Metadata = { title: 'Категории' };

export default function CategoriesPage() {
  return (
    <RequirePermission all={[Permission.CATALOG_READ]}>
      {/* Выбранная категория читается из адреса (useSearchParams). */}
      <Suspense fallback={<PageLoader />}>
        <CategoriesScreen />
      </Suspense>
    </RequirePermission>
  );
}
