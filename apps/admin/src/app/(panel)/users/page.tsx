import type { Metadata } from 'next';

import { UsersScreen } from '@/components/users/UsersScreen';

export const metadata: Metadata = { title: 'Пользователи' };

export default function Page() {
  return <UsersScreen />;
}
