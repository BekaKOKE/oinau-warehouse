import type { Metadata } from 'next';
import { Suspense } from 'react';

import { ImportExportScreen } from '@/components/imports/ImportExportScreen';
import { PageLoader } from '@/components/ui/States';

export const metadata: Metadata = { title: 'Импорт / экспорт' };

export default function Page() {
  // Вкладка читается из адреса (useSearchParams) — нужна граница Suspense.
  return (
    <Suspense fallback={<PageLoader />}>
      <ImportExportScreen />
    </Suspense>
  );
}
