'use client';

import type { ReactNode } from 'react';

import { SessionProvider } from '@/components/session/SessionProvider';
import { ConfirmProvider } from '@/components/ui/Dialog';
import { ToastProvider } from '@/components/ui/Toast';

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <ToastProvider>
      <ConfirmProvider>
        <SessionProvider>{children}</SessionProvider>
      </ConfirmProvider>
    </ToastProvider>
  );
}
