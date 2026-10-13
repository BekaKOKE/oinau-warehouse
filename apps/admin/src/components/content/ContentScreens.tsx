'use client';

/**
 * Раздел «Контент»: обзор шести разделов CMS и экран редактирования.
 *
 * Разделы — фиксированный набор backend; каждый живёт по своему адресу
 * (/content/faq), навигация между ними и уход из админки проверяют
 * несохранённые изменения.
 */

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useState, type ComponentType } from 'react';

import { RequirePermission } from '@/components/session/AuthGate';
import { Badge } from '@/components/ui/Badge';
import { ButtonLink } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { Card, PageHeader } from '@/components/ui/Layout';
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/States';
import { contentApi } from '@/lib/api/endpoints';
import type { ContentSectionKey, ContentSectionSummary } from '@/lib/api/types';
import { Permission } from '@/lib/auth/permissions';
import { SITE_URL } from '@/lib/config';
import { contactsSpec } from '@/lib/content/contacts';
import { deliverySpec } from '@/lib/content/delivery';
import { faqSpec } from '@/lib/content/faq';
import { homeSpec } from '@/lib/content/home';
import { requisitesSpec } from '@/lib/content/requisites';
import {
  CONTENT_SECTIONS,
  isSectionKey,
  sectionMeta,
  sectionSiteUrl,
} from '@/lib/content/sections';
import { servicesSpec } from '@/lib/content/services';
import { settingsSpec } from '@/lib/content/settings';
import { formatDateTime } from '@/lib/format';
import { useLeaveGuard } from '@/lib/hooks/useLeaveGuard';
import { useQuery } from '@/lib/hooks/useQuery';

import { ContactsFields } from './sections/ContactsFields';
import { DeliveryFields } from './sections/DeliveryFields';
import { FaqFields } from './sections/FaqFields';
import { HomeFields } from './sections/HomeFields';
import { RequisitesFields } from './sections/RequisitesFields';
import { ServicesFields } from './sections/ServicesFields';
import { SettingsFields } from './sections/SettingsFields';
import { SectionEditor } from './SectionEditor';
import styles from './Content.module.css';

const ROOT_CRUMB = { label: 'Контент', href: '/content' };

function SiteLink({
  sectionKey,
  compact = false,
}: {
  sectionKey: ContentSectionKey;
  compact?: boolean;
}) {
  const meta = sectionMeta(sectionKey);
  return (
    <a
      className={compact ? styles.siteLinkCompact : styles.siteLink}
      href={sectionSiteUrl(SITE_URL, sectionKey)}
      target="_blank"
      rel="noreferrer"
      aria-label={`${meta.siteLabel}: ${meta.label} (на сайте, в новой вкладке)`}
    >
      <Icon name="external" size={14} /> {meta.siteLabel}
    </a>
  );
}

// ------------------------------------------------------------------ обзор

/**
 * Данные запрашиваются только внутри `RequirePermission`: роли без
 * права не нужен ни запрос, ни гарантированный 403.
 */
export function ContentOverview() {
  return (
    <RequirePermission all={[Permission.CONTENT_WRITE]}>
      <ContentOverviewPanel />
    </RequirePermission>
  );
}

function ContentOverviewPanel() {
  const query = useQuery((signal) => contentApi.list({ signal }), []);
  const byKey = new Map<string, ContentSectionSummary>(
    (query.data ?? []).map((item) => [item.key, item]),
  );

  return (
    <>
      <PageHeader
        title="Контент"
        description="Тексты и настройки публичного сайта. Разделы структурированы: меняются данные, дизайн страниц остаётся прежним."
      />
      {query.status === 'error' && !query.data ? (
        <Card>
          <ErrorState error={query.error} onRetry={query.reload} />
        </Card>
      ) : query.data && query.data.length === 0 ? (
        <Card>
          <EmptyState title="Разделов нет" description="Backend не вернул ни одного раздела CMS." />
        </Card>
      ) : (
        <ul className={styles.overview} aria-label="Разделы контента" aria-busy={!query.data}>
          {CONTENT_SECTIONS.map((section) => {
            const summary = byKey.get(section.key);
            return (
              <li key={section.key} className={styles.overviewCard}>
                <div className={styles.overviewHead}>
                  <h2 className={styles.overviewTitle}>
                    <Link href={`/content/${section.key}`}>{section.label}</Link>
                  </h2>
                  {!query.data ? (
                    <Skeleton width={90} height={20} />
                  ) : summary?.is_configured ? (
                    <Badge tone="success" dot>
                      Заполнен
                    </Badge>
                  ) : (
                    <Badge tone="warning" dot>
                      Не заполнен
                    </Badge>
                  )}
                </div>
                <p className={styles.overviewText}>{section.description}</p>
                <p className={styles.muted}>
                  {!query.data ? (
                    <Skeleton width={160} height={12} />
                  ) : summary?.updated_at ? (
                    `Изменён ${formatDateTime(summary.updated_at)}`
                  ) : (
                    'Сайт показывает тексты по умолчанию'
                  )}
                </p>
                <div className={styles.overviewActions}>
                  <ButtonLink href={`/content/${section.key}`} size="sm" icon="edit">
                    Редактировать
                  </ButtonLink>
                  <SiteLink sectionKey={section.key} compact />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}

// ------------------------------------------------------ экран раздела

type HostProps = { onDirtyChange: (dirty: boolean) => void };

/** Раздел → форма и поля. Типы связаны: форма главной не попадёт в FAQ. */
const EDITORS: Record<ContentSectionKey, ComponentType<HostProps>> = {
  home: (props) => (
    <SectionEditor sectionKey="home" spec={homeSpec} Fields={HomeFields} {...props} />
  ),
  contacts: (props) => (
    <SectionEditor sectionKey="contacts" spec={contactsSpec} Fields={ContactsFields} {...props} />
  ),
  delivery: (props) => (
    <SectionEditor sectionKey="delivery" spec={deliverySpec} Fields={DeliveryFields} {...props} />
  ),
  faq: (props) => <SectionEditor sectionKey="faq" spec={faqSpec} Fields={FaqFields} {...props} />,
  requisites: (props) => (
    <SectionEditor
      sectionKey="requisites"
      spec={requisitesSpec}
      Fields={RequisitesFields}
      {...props}
    />
  ),
  settings: (props) => (
    <SectionEditor sectionKey="settings" spec={settingsSpec} Fields={SettingsFields} {...props} />
  ),
  services: (props) => (
    <SectionEditor sectionKey="services" spec={servicesSpec} Fields={ServicesFields} {...props} />
  ),
};

function SectionNotFound() {
  return (
    <>
      <PageHeader title="Раздел не найден" breadcrumbs={[ROOT_CRUMB]} />
      <Card>
        <EmptyState
          icon="content"
          title="Такого раздела контента нет"
          description="Разделы CMS фиксированы: главная, контакты, доставка, FAQ, реквизиты и настройки."
          action={
            <ButtonLink href="/content" icon="chevronLeft">
              Ко всем разделам
            </ButtonLink>
          }
        />
      </Card>
    </>
  );
}

/**
 * Данные запрашиваются только внутри `RequirePermission`: роли без
 * права не нужен ни запрос, ни гарантированный 403.
 */
export function ContentSectionScreen({ section }: { section: string }) {
  return (
    <RequirePermission all={[Permission.CONTENT_WRITE]}>
      <ContentSectionPanel section={section} />
    </RequirePermission>
  );
}

function ContentSectionPanel({ section }: { section: string }) {
  if (!isSectionKey(section)) return <SectionNotFound />;
  return <SectionScreen key={section} sectionKey={section} />;
}

function SectionScreen({ sectionKey }: { sectionKey: ContentSectionKey }) {
  const router = useRouter();
  const [dirty, setDirty] = useState(false);
  const confirmLeave = useLeaveGuard(dirty);
  const meta = sectionMeta(sectionKey);
  const Editor = EDITORS[sectionKey];
  const onDirtyChange = useCallback((value: boolean) => setDirty(value), []);

  // На узком экране вкладки прокручиваются: активная не должна прятаться за краем.
  useEffect(() => {
    document
      .getElementById(`content-tab-${sectionKey}`)
      ?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
  }, [sectionKey]);

  const open = async (key: ContentSectionKey) => {
    if (key === sectionKey) return;
    if (!(await confirmLeave())) return;
    setDirty(false);
    router.push(`/content/${key}`);
  };

  return (
    <>
      <PageHeader
        breadcrumbs={[ROOT_CRUMB, { label: meta.label }]}
        title={meta.label}
        description={meta.description}
        actions={<SiteLink sectionKey={sectionKey} />}
      />
      <nav className={styles.tabs} aria-label="Разделы контента">
        {CONTENT_SECTIONS.map((item) => (
          <button
            key={item.key}
            type="button"
            id={`content-tab-${item.key}`}
            aria-current={item.key === sectionKey ? 'page' : undefined}
            className={`${styles.tab} ${item.key === sectionKey ? styles.tabActive : ''}`}
            onClick={() => void open(item.key)}
          >
            {item.label}
          </button>
        ))}
      </nav>
      <Editor onDirtyChange={onDirtyChange} />
    </>
  );
}
