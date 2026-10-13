import type { ReactNode } from 'react';

import { AppShell } from '@/components/layout/AppShell';
import { AuthGate } from '@/components/session/AuthGate';

export default function PanelLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGate>
      <AppShell>{children}</AppShell>
    </AuthGate>
  );
}
