'use client';

import {
  emptyDeliveryMethod,
  MAX_DELIVERY_METHODS,
  type DeliveryForm,
} from '@/lib/content/delivery';
import { isLocEmpty } from '@/lib/content/fields';

import { ListEditor, LocField } from '../fields';
import { Panel } from '../FormContext';
import type { FieldsProps } from '../SectionEditor';
import { SeoPanel } from '../SeoPanel';

export function DeliveryFields({ form, update }: FieldsProps<DeliveryForm>) {
  const set = <F extends keyof DeliveryForm>(field: F, value: DeliveryForm[F]) =>
    update((current) => ({ ...current, [field]: value }));

  return (
    <>
      <Panel title="Вступление" description="Текст в начале страницы доставки." paths={['intro']}>
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
        title="Способы доставки"
        description="Самовывоз, доставка по городу, транспортные компании. Порядок — как в списке."
        paths={['methods']}
        summary={`${form.methods.length} из ${MAX_DELIVERY_METHODS}`}
      >
        <ListEditor
          path="methods"
          items={form.methods}
          onChange={(methods) => set('methods', methods)}
          max={MAX_DELIVERY_METHODS}
          create={emptyDeliveryMethod}
          itemLabel={(index) => `Способ ${index + 1}`}
          itemSummary={(item) => item.title.ru ?? ''}
          isFilled={(item) => !isLocEmpty(item.title) || !isLocEmpty(item.text)}
          addLabel="Добавить способ"
          emptyTitle="Способов доставки нет"
        >
          {(item, index, patch) => (
            <>
              <LocField
                label="Название"
                path={`methods.${index}.title`}
                kind="line"
                required
                value={item.title}
                onChange={(title) => patch({ title })}
                placeholder="Самовывоз со склада"
              />
              <LocField
                label="Условия"
                path={`methods.${index}.text`}
                kind="text"
                rows={3}
                value={item.text}
                onChange={(text) => patch({ text })}
              />
            </>
          )}
        </ListEditor>
      </Panel>

      <Panel title="Оплата" description="Способы и условия оплаты." paths={['payment']}>
        <LocField
          label="Оплата"
          path="payment"
          kind="text"
          value={form.payment}
          onChange={(payment) => set('payment', payment)}
        />
      </Panel>

      <SeoPanel value={form.seo} onChange={(seo) => set('seo', seo)} />
    </>
  );
}
