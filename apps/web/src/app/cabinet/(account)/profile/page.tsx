import type { Metadata } from 'next';

import { ProfileForm } from '@/components/cabinet/ProfileForm';

export const metadata: Metadata = { title: 'Профиль' };

export default function CabinetProfilePage() {
  return <ProfileForm />;
}
