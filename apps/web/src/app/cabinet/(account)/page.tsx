import type { Metadata } from 'next';

import { CabinetDashboard } from '@/components/cabinet/CabinetDashboard';

export const metadata: Metadata = { title: 'Личный кабинет' };

export default function CabinetHomePage() {
  return <CabinetDashboard />;
}
