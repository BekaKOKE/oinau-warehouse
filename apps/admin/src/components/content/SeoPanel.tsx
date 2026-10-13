'use client';

import type { SeoForm } from '@/lib/content/seo';
import { isLocEmpty } from '@/lib/content/fields';

import { LocField } from './fields';
import { Panel } from './FormContext';
import { MediaField } from './MediaField';
import styles from './Content.module.css';

const SEO_TEXT_FIELDS = ['title', 'description', 'og_title', 'og_description'] as const;

export function SeoPanel({
  value,
  onChange,
  title = 'SEO',
  description = 'Заголовок и описание для поисковиков и соцсетей. Пустое поле берётся из SEO по умолчанию («Настройки»).',
  defaultOpen = false,
}: {
  value: SeoForm;
  onChange: (value: SeoForm) => void;
  title?: string;
  description?: string;
  defaultOpen?: boolean;
}) {
  const filled =
    SEO_TEXT_FIELDS.filter((field) => !isLocEmpty(value[field])).length + (value.og_image ? 1 : 0);
  const patch = (next: Partial<SeoForm>) => onChange({ ...value, ...next });

  return (
    <Panel
      title={title}
      description={description}
      paths={['seo']}
      defaultOpen={defaultOpen}
      summary={filled > 0 ? `Заполнено ${filled} из 5` : 'Не заполнено'}
    >
      <div className={styles.grid2}>
        <LocField
          label="Заголовок (title)"
          path="seo.title"
          kind="line"
          value={value.title}
          onChange={(title) => patch({ title })}
          hint="Заголовок вкладки браузера и результата поиска"
        />
        <LocField
          label="Заголовок для соцсетей (og:title)"
          path="seo.og_title"
          kind="line"
          value={value.og_title}
          onChange={(og_title) => patch({ og_title })}
          hint="Пусто — как заголовок (title)"
        />
        <LocField
          label="Описание (description)"
          path="seo.description"
          kind="seo"
          value={value.description}
          onChange={(description) => patch({ description })}
          hint="Поисковики показывают около 160 символов"
        />
        <LocField
          label="Описание для соцсетей (og:description)"
          path="seo.og_description"
          kind="seo"
          value={value.og_description}
          onChange={(og_description) => patch({ og_description })}
          hint="Пусто — как описание (description)"
        />
      </div>
      <MediaField
        label="Изображение для соцсетей (og:image)"
        path="seo.og_image"
        value={value.og_image}
        onChange={(og_image) => patch({ og_image })}
        hint="Показывается при отправке ссылки в мессенджер или соцсеть. Лучше 1200×630."
      />
    </Panel>
  );
}
