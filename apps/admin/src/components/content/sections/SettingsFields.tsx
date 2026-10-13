'use client';

import Link from 'next/link';

import { Icon } from '@/components/ui/Icon';
import { isBlank } from '@/lib/content/fields';
import {
  emptySocialLink,
  isSocialNetwork,
  MAX_SOCIAL_LINKS,
  SOCIAL_NETWORK_LABELS,
  SOCIAL_NETWORKS,
  type SettingsForm,
} from '@/lib/content/settings';

import { ListEditor, LocField, SelectField, TextField } from '../fields';
import { Panel } from '../FormContext';
import type { FieldsProps } from '../SectionEditor';
import { SeoPanel } from '../SeoPanel';
import styles from '../Content.module.css';

const NETWORK_OPTIONS = SOCIAL_NETWORKS.map((network) => ({
  value: network,
  label: SOCIAL_NETWORK_LABELS[network],
}));

export function SettingsFields({ form, update }: FieldsProps<SettingsForm>) {
  const set = <F extends keyof SettingsForm>(field: F, value: SettingsForm[F]) =>
    update((current) => ({ ...current, [field]: value }));

  return (
    <>
      <p className={styles.note}>
        <Icon name="info" size={16} />
        <span>
          Телефоны, email и WhatsApp сайта задаются в разделе{' '}
          <Link href="/content/contacts">«Контакты»</Link>.
        </span>
      </p>

      <Panel
        title="Сайт"
        description="Название в подвале и заголовках страниц."
        paths={['site_name']}
      >
        <LocField
          label="Название сайта"
          path="site_name"
          kind="line"
          value={form.site_name}
          onChange={(value) => set('site_name', value)}
          placeholder="OINAU PRO"
        />
      </Panel>

      <SeoPanel
        title="SEO по умолчанию"
        description="Подставляется на страницах, где своё SEO не заполнено."
        defaultOpen
        value={form.seo}
        onChange={(seo) => set('seo', seo)}
      />

      <Panel
        title="Соцсети"
        description="Ссылки в подвале сайта. Каждая сеть — один раз, только https://."
        paths={['social_links']}
        summary={`${form.social_links.length} из ${MAX_SOCIAL_LINKS}`}
      >
        <ListEditor
          path="social_links"
          items={form.social_links}
          onChange={(links) => set('social_links', links)}
          max={MAX_SOCIAL_LINKS}
          create={emptySocialLink}
          itemLabel={(index) => `Ссылка ${index + 1}`}
          itemSummary={(item) => (item.network ? SOCIAL_NETWORK_LABELS[item.network] : '')}
          isFilled={(item) => Boolean(item.network) || !isBlank(item.url)}
          addLabel="Добавить соцсеть"
          emptyTitle="Ссылок на соцсети нет"
        >
          {(item, index, patch) => (
            <div className={styles.grid2}>
              <SelectField
                label="Соцсеть"
                path={`social_links.${index}.network`}
                required
                value={item.network}
                options={NETWORK_OPTIONS}
                placeholder="Выберите"
                onChange={(value) => patch({ network: isSocialNetwork(value) ? value : '' })}
              />
              <TextField
                label="Ссылка"
                path={`social_links.${index}.url`}
                required
                inputMode="url"
                value={item.url}
                onChange={(url) => patch({ url })}
                placeholder="https://instagram.com/oinau.pro"
                hint={
                  item.network === 'WHATSAPP'
                    ? 'В подвале WhatsApp берётся из раздела «Контакты»'
                    : undefined
                }
                mono
              />
            </div>
          )}
        </ListEditor>
      </Panel>
    </>
  );
}
