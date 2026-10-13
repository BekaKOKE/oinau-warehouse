import type { Metadata } from 'next';
import { Suspense } from 'react';

import { LoginScreen } from '@/components/auth/LoginScreen';

export const metadata: Metadata = { title: 'Вход' };

export default function LoginPage() {
  // useSearchParams внутри экрана требует границы Suspense при сборке.
  return (
    <Suspense>
      <LoginScreen />
    </Suspense>
  );
}
