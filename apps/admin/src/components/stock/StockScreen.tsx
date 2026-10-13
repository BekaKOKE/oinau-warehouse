'use client';

/**
 * Раздел «Склад»: остатки по товарам и справочник складов.
 *
 * Вкладка живёт в адресе (?tab=warehouses), фильтры остатков — тоже,
 * так что ссылку на выборку можно переслать.
 */

import { usePathname, useRouter, useSearchParams } from 'next/navigation';

import { RequirePermission } from '@/components/session/AuthGate';
import { PageHeader } from '@/components/ui/Layout';
import { Permission } from '@/lib/auth/permissions';

import { StockList } from './StockList';
import { WarehousesPanel } from './WarehousesPanel';
import styles from './Stock.module.css';

const TABS = [
  { id: 'stock', label: 'Остатки' },
  { id: 'warehouses', label: 'Склады' },
] as const;

type TabId = (typeof TABS)[number]['id'];

/**
 * Данные запрашиваются только внутри `RequirePermission`: роли без
 * права не нужен ни запрос, ни гарантированный 403.
 */
export function StockScreen() {
  return (
    <RequirePermission all={[Permission.CATALOG_READ]}>
      <StockPanel />
    </RequirePermission>
  );
}

function StockPanel() {
  const router = useRouter();
  const pathname = usePathname();
  const tab: TabId = useSearchParams().get('tab') === 'warehouses' ? 'warehouses' : 'stock';

  return (
    <>
      <PageHeader
        title="Склад"
        description="Фактические остатки по складам, публичное наличие и справочник складов."
      />
      <div className={styles.tabs} role="tablist" aria-label="Разделы склада">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            id={`stock-tab-${item.id}`}
            aria-selected={tab === item.id}
            aria-controls={`stock-panel-${item.id}`}
            className={`${styles.tab} ${tab === item.id ? styles.tabActive : ''}`}
            onClick={() =>
              router.replace(item.id === 'stock' ? pathname : `${pathname}?tab=${item.id}`, {
                scroll: false,
              })
            }
          >
            {item.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`stock-panel-${tab}`} aria-labelledby={`stock-tab-${tab}`}>
        {tab === 'stock' ? <StockList /> : <WarehousesPanel />}
      </div>
    </>
  );
}
