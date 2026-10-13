'use client';

import { isLocEmpty } from '@/lib/content/fields';
import { emptyAdvantage, MAX_ADVANTAGES, splitHeroTitle, type HomeForm } from '@/lib/content/home';

import { ListEditor, LocField, TextField } from '../fields';
import { GroupError, Panel } from '../FormContext';
import { MediaField } from '../MediaField';
import type { FieldsProps } from '../SectionEditor';
import { SeoPanel } from '../SeoPanel';
import styles from '../Content.module.css';

export function HomeFields({ form, update }: FieldsProps<HomeForm>) {
  const hero = form.hero;
  const patchHero = (patch: Partial<HomeForm['hero']>) =>
    update((current) => ({ ...current, hero: { ...current.hero, ...patch } }));
  const patchAbout = (patch: Partial<HomeForm['about']>) =>
    update((current) => ({ ...current, about: { ...current.about, ...patch } }));
  const title = splitHeroTitle(hero.title.ru ?? '');

  return (
    <>
      <Panel
        title="Первый экран"
        description="Заголовок, подзаголовок и кнопка. Если блок пуст, сайт показывает тексты по умолчанию."
        paths={['hero']}
      >
        <GroupError path="hero" />
        <LocField
          label="Заголовок"
          path="hero.title"
          kind="line"
          required
          value={hero.title}
          onChange={(value) => patchHero({ title: value })}
          placeholder="Комплектующие для современных площадок"
        />
        {title.head ? (
          <p className={styles.titlePreview} aria-label="Как выделится заголовок">
            На сайте: {title.head} {title.accent ? <mark>{title.accent}</mark> : null} {title.tail}
            <span className={styles.muted}> — акцент на предпоследнем слове</span>
          </p>
        ) : null}
        <LocField
          label="Подзаголовок"
          path="hero.subtitle"
          kind="short"
          value={hero.subtitle}
          onChange={(value) => patchHero({ subtitle: value })}
        />
        <div className={styles.grid2}>
          <LocField
            label="Текст кнопки"
            path="hero.cta_label"
            kind="line"
            value={hero.cta_label}
            onChange={(value) => patchHero({ cta_label: value })}
            placeholder="Перейти в каталог"
            hint="Задаётся вместе со ссылкой"
          />
          <TextField
            label="Ссылка кнопки"
            path="hero.cta_url"
            value={hero.cta_url}
            onChange={(value) => patchHero({ cta_url: value })}
            placeholder="/catalog"
            hint="Путь на сайте (/catalog) или адрес https://…"
            inputMode="url"
            mono
          />
        </div>
        <MediaField
          label="Изображение первого экрана"
          path="hero.image"
          value={hero.image}
          onChange={(value) => patchHero({ image: value })}
          hint="Хранится в разделе. Текущий дизайн главной использует утверждённую фотографию первого экрана и это поле не выводит."
        />
      </Panel>

      <Panel
        title="Преимущества"
        description="Блок «Почему с нами работают». Порядок — как в списке."
        paths={['advantages']}
        summary={`${form.advantages.length} из ${MAX_ADVANTAGES}`}
      >
        <ListEditor
          path="advantages"
          items={form.advantages}
          onChange={(advantages) => update((current) => ({ ...current, advantages }))}
          max={MAX_ADVANTAGES}
          create={emptyAdvantage}
          itemLabel={(index) => `Преимущество ${index + 1}`}
          itemSummary={(item) => item.title.ru ?? ''}
          isFilled={(item) => !isLocEmpty(item.title) || !isLocEmpty(item.text)}
          addLabel="Добавить преимущество"
          emptyTitle="Преимуществ нет"
          emptyDescription="Без них блок на главной не показывается."
        >
          {(item, index, patch) => (
            <>
              <LocField
                label="Заголовок"
                path={`advantages.${index}.title`}
                kind="line"
                required
                value={item.title}
                onChange={(value) => patch({ title: value })}
              />
              <LocField
                label="Текст"
                path={`advantages.${index}.text`}
                kind="short"
                value={item.text}
                onChange={(value) => patch({ text: value })}
              />
            </>
          )}
        </ListEditor>
      </Panel>

      <Panel
        title="О компании"
        description="Текстовый блок внизу главной. Пустой блок не показывается."
        paths={['about']}
      >
        <LocField
          label="Заголовок"
          path="about.title"
          kind="line"
          value={form.about.title}
          onChange={(value) => patchAbout({ title: value })}
          placeholder="О компании"
          hint="Пусто — «О компании»"
        />
        <LocField
          label="Текст"
          path="about.text"
          kind="text"
          required={!isLocEmpty(form.about.title)}
          value={form.about.text}
          onChange={(value) => patchAbout({ text: value })}
          hint="Абзацы разделяются переводом строки"
        />
      </Panel>

      <SeoPanel value={form.seo} onChange={(seo) => update((current) => ({ ...current, seo }))} />
    </>
  );
}
