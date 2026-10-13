'use client';

/**
 * Раздел «Импорт / экспорт»: выгрузка каталога, загрузка книги Excel
 * и массовый импорт товаров ZIP-архивом (книга + фото + схемы).
 *
 * Права те же, что в backend: экспорт, шаблон, предпросмотр и история —
 * `catalog.read`; применение Excel-импорта — `catalog.write`; загрузка
 * и применение ZIP — `catalog.write` и `media.upload`.
 *
 * Вкладка живёт в адресе (?tab=bundle): ссылку на массовый импорт
 * можно переслать коллеге.
 */

import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useState } from 'react';

import { RequirePermission } from '@/components/session/AuthGate';
import { PageHeader } from '@/components/ui/Layout';
import { Permission } from '@/lib/auth/permissions';

import { BundleWizard } from './BundleWizard';
import { ExportPanel } from './ExportPanel';
import { ImportHistory } from './ImportHistory';
import { ImportWizard } from './ImportWizard';
import styles from './ImportExport.module.css';

const TABS = [
  { id: 'excel', label: 'Импорт Excel' },
  { id: 'bundle', label: 'Массовый импорт (ZIP)' },
] as const;

type TabId = (typeof TABS)[number]['id'];

export function ImportExportScreen() {
  return (
    <RequirePermission all={[Permission.CATALOG_READ]}>
      <ImportExportPanel />
    </RequirePermission>
  );
}

function ImportExportPanel() {
  const router = useRouter();
  const pathname = usePathname();
  const tab: TabId = useSearchParams().get('tab') === 'bundle' ? 'bundle' : 'excel';
  // Применённый импорт меняет каталог — история перечитывается.
  const [applied, setApplied] = useState(0);
  const onCommitted = useCallback(() => setApplied((value) => value + 1), []);

  return (
    <>
      <PageHeader
        title="Импорт / экспорт"
        description="Выгрузка каталога в XLSX, загрузка изменений из Excel и массовый импорт товаров с фото и схемами."
      />
      <div className={styles.tabs} role="tablist" aria-label="Способ импорта">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            id={`import-tab-${item.id}`}
            aria-selected={tab === item.id}
            aria-controls={`import-panel-${item.id}`}
            className={`${styles.tab} ${tab === item.id ? styles.tabActive : ''}`}
            onClick={() =>
              router.replace(item.id === 'excel' ? pathname : `${pathname}?tab=${item.id}`, {
                scroll: false,
              })
            }
          >
            {item.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`import-panel-${tab}`} aria-labelledby={`import-tab-${tab}`}>
        {tab === 'bundle' ? (
          <BundleWizard onCommitted={onCommitted} />
        ) : (
          <>
            <ExportPanel />
            <ImportWizard onCommitted={onCommitted} />
            <ImportHistory refreshKey={applied} />
          </>
        )}
      </div>
    </>
  );
}
