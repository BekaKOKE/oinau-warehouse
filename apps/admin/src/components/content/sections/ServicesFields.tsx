'use client';

import { isLocEmpty } from '@/lib/content/fields';
import {
  emptyService,
  emptyServiceDetail,
  MAX_SERVICE_DETAILS,
  MAX_SERVICES,
  type ServicesForm,
} from '@/lib/content/services';

import { ListEditor, LocField, TextField } from '../fields';
import { Panel } from '../FormContext';
import { MediaField } from '../MediaField';
import type { FieldsProps } from '../SectionEditor';
import { SeoPanel } from '../SeoPanel';

export function ServicesFields({ form, update }: FieldsProps<ServicesForm>) {
  const set = <F extends keyof ServicesForm>(field: F, value: ServicesForm[F]) =>
    update((current) => ({ ...current, [field]: value }));

  return (
    <>
      <Panel title="Вступление" description="Текст в начале страницы услуг." paths={['intro']}>
        <LocField
          label="Вступление"
          path="intro"
          kind="text"
          value={form.intro}
          onChange={(intro) => set('intro', intro)}
          hint="Абзацы разделяются переводом строки"
        />
      </Panel>

      <Panel
        title="Услуги"
        description="Обжимка и обрезка канатов, металлорезка и другие работы. Порядок на сайте — как в списке."
        paths={['items']}
        summary={`${form.items.length} из ${MAX_SERVICES}`}
      >
        <ListEditor
          path="items"
          items={form.items}
          onChange={(items) => set('items', items)}
          max={MAX_SERVICES}
          create={emptyService}
          itemLabel={(index) => `Услуга ${index + 1}`}
          itemSummary={(item) => item.title.ru ?? ''}
          isFilled={(item) => !isLocEmpty(item.title) || Boolean(item.slug)}
          addLabel="Добавить услугу"
          emptyTitle="Услуг нет"
        >
          {(item, index, patch) => (
            <>
              <LocField
                label="Название"
                path={`items.${index}.title`}
                kind="line"
                required
                value={item.title}
                onChange={(title) => patch({ title })}
                placeholder="Обжимка канатов"
              />
              <TextField
                label="Адрес на странице"
                path={`items.${index}.slug`}
                required
                mono
                value={item.slug}
                onChange={(slug) => patch({ slug })}
                placeholder="obzhimka-kanatov"
                hint="Ссылка на услугу: /services#slug. Строчная латиница, цифры и дефис."
              />
              <LocField
                label="Краткое описание"
                path={`items.${index}.summary`}
                kind="short"
                rows={3}
                value={item.summary}
                onChange={(summary) => patch({ summary })}
              />
              <ListEditor
                path={`items.${index}.details`}
                items={item.details}
                onChange={(details) => patch({ details })}
                max={MAX_SERVICE_DETAILS}
                create={emptyServiceDetail}
                itemLabel={(detailIndex) => `Пункт ${detailIndex + 1}`}
                itemSummary={(detail) => detail.text.ru ?? ''}
                isFilled={(detail) => !isLocEmpty(detail.text)}
                addLabel="Добавить пункт «Что делаем»"
                emptyTitle="Пунктов «Что делаем» нет"
              >
                {(detail, detailIndex, patchDetail) => (
                  <LocField
                    label="Что делаем"
                    path={`items.${index}.details.${detailIndex}`}
                    kind="line"
                    value={detail.text}
                    onChange={(text) => patchDetail({ text })}
                    placeholder="Алюминиевые и стальные втулки"
                  />
                )}
              </ListEditor>
              <LocField
                label="Условия / стоимость"
                path={`items.${index}.price_note`}
                kind="line"
                value={item.priceNote}
                onChange={(priceNote) => patch({ priceNote })}
                placeholder="Стоимость — по объёму партии"
              />
              <LocField
                label="Текст кнопки"
                path={`items.${index}.cta_label`}
                kind="line"
                value={item.ctaLabel}
                onChange={(ctaLabel) => patch({ ctaLabel })}
                hint="Пусто — «Оставить заявку»"
              />
              <MediaField
                label="Изображение"
                path={`items.${index}.image`}
                value={item.image}
                onChange={(image) => patch({ image })}
                hint="Необязательно. Фото работы или изделия."
              />
            </>
          )}
        </ListEditor>
      </Panel>

      <SeoPanel value={form.seo} onChange={(seo) => set('seo', seo)} />
    </>
  );
}
