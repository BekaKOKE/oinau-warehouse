import type { Metadata } from 'next';

import { IntegrationScreen } from '@/components/integration/IntegrationScreen';

export const metadata: Metadata = { title: 'Интеграции' };

export default function Page() {
  return <IntegrationScreen />;
}
