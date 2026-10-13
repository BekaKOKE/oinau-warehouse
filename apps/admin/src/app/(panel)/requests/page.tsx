import type { Metadata } from 'next';
import { Suspense } from 'react';

import { RequestsList } from '@/components/requests/RequestsList';
import { RequirePermission } from '@/components/session/AuthGate';
import { PageLoader } from '@/components/ui/States';
import { Permission } from '@/lib/auth/permissions';

export const metadata: Metadata = { title: 'Заявки' };

export default function RequestsPage() {
  return (
    <RequirePermission all={[Permission.REQUEST_READ]}>
      {/* Фильтры читаются из адреса (useSearchParams) — нужна граница Suspense. */}
      <Suspense fallback={<PageLoader />}>
        <RequestsList />
      </Suspense>
    </RequirePermission>
  );
}
