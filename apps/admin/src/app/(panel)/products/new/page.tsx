import type { Metadata } from 'next';

import { ProductCreateScreen } from '@/components/products/ProductCreateScreen';
import { RequirePermission } from '@/components/session/AuthGate';
import { Permission } from '@/lib/auth/permissions';

export const metadata: Metadata = { title: 'Новый товар' };

export default function NewProductPage() {
  return (
    <RequirePermission all={[Permission.CATALOG_WRITE]}>
      <ProductCreateScreen />
    </RequirePermission>
  );
}
