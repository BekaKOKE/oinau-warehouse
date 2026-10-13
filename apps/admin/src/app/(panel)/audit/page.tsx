import type { Metadata } from 'next';

import { AuditScreen } from '@/components/audit/AuditScreen';

export const metadata: Metadata = { title: 'Аудит' };

export default function Page() {
  return <AuditScreen />;
}
