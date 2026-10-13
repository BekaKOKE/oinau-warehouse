import type { Metadata } from 'next';

import { RequestDetailScreen } from '@/components/requests/RequestDetailScreen';
import { RequirePermission } from '@/components/session/AuthGate';
import { Permission } from '@/lib/auth/permissions';

export const metadata: Metadata = { title: 'Заявка' };

export default async function RequestPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  // Нечисловой id не отправляется на backend: экран сразу покажет «не найдена».
  const numeric = /^\d+$/.test(id) ? Number(id) : Number.NaN;
  return (
    <RequirePermission all={[Permission.REQUEST_READ]}>
      <RequestDetailScreen id={numeric} />
    </RequirePermission>
  );
}
