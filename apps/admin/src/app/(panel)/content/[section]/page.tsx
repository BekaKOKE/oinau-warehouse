import type { Metadata } from 'next';

import { ContentSectionScreen } from '@/components/content/ContentScreens';
import { RequirePermission } from '@/components/session/AuthGate';
import { Permission } from '@/lib/auth/permissions';

export const metadata: Metadata = { title: 'Контент' };

export default async function ContentSectionPage({
  params,
}: {
  params: Promise<{ section: string }>;
}) {
  const { section } = await params;
  // Чтение и запись CMS в backend — одно право content.write
  // (отдельного content.read нет), поэтому и экран требует его.
  return (
    <RequirePermission all={[Permission.CONTENT_WRITE]}>
      <ContentSectionScreen section={section} />
    </RequirePermission>
  );
}
