import type { Metadata } from 'next';

import { ContentOverview } from '@/components/content/ContentScreens';
import { RequirePermission } from '@/components/session/AuthGate';
import { Permission } from '@/lib/auth/permissions';

export const metadata: Metadata = { title: 'Контент' };

export default function ContentPage() {
  return (
    <RequirePermission all={[Permission.CONTENT_WRITE]}>
      <ContentOverview />
    </RequirePermission>
  );
}
