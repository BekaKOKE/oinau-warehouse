'use client';

import {
  emptyEmail,
  emptyPhone,
  MAX_EMAILS,
  MAX_PHONES,
  type ContactsForm,
} from '@/lib/content/contacts';
import { isBlank, isLocEmpty } from '@/lib/content/fields';

import { ListEditor, LocField, TextField } from '../fields';
import { GroupError, Panel } from '../FormContext';
import type { FieldsProps } from '../SectionEditor';
import { SeoPanel } from '../SeoPanel';
import styles from '../Content.module.css';

export function ContactsFields({ form, update }: FieldsProps<ContactsForm>) {
  const set = <F extends keyof ContactsForm>(field: F, value: ContactsForm[F]) =>
    update((current) => ({ ...current, [field]: value }));

  return (
    <>
      <Panel
        title="Телефоны"
        description="Выводятся в подвале и на странице контактов. Первый номер — основной."
        paths={['phones']}
        summary={`${form.phones.length} из ${MAX_PHONES}`}
      >
        <ListEditor
          path="phones"
          items={form.phones}
          onChange={(phones) => set('phones', phones)}
          max={MAX_PHONES}
          create={emptyPhone}
          itemLabel={(index) => `Телефон ${index + 1}`}
          itemSummary={(item) => item.number.trim()}
          isFilled={(item) => !isBlank(item.number) || !isLocEmpty(item.label)}
          addLabel="Добавить телефон"
          emptyTitle="Телефонов нет"
          emptyDescription="На сайте останется только форма заявки."
        >
          {(item, index, patch) => (
            <div className={styles.grid2}>
              <TextField
                label="Номер"
                path={`phones.${index}.number`}
                type="tel"
                inputMode="tel"
                required
                value={item.number}
                onChange={(number) => patch({ number })}
                placeholder="+7 727 000 00 00"
              />
              <LocField
                label="Подпись"
                path={`phones.${index}.label`}
                kind="line"
                value={item.label}
                onChange={(label) => patch({ label })}
                placeholder="Отдел продаж"
              />
            </div>
          )}
        </ListEditor>
      </Panel>

      <Panel
        title="Email"
        description="Выводятся в подвале и на странице контактов."
        paths={['emails']}
        summary={`${form.emails.length} из ${MAX_EMAILS}`}
      >
        <ListEditor
          path="emails"
          items={form.emails}
          onChange={(emails) => set('emails', emails)}
          max={MAX_EMAILS}
          create={emptyEmail}
          itemLabel={(index) => `Email ${index + 1}`}
          itemSummary={(item) => item.email.trim()}
          isFilled={(item) => !isBlank(item.email) || !isLocEmpty(item.label)}
          addLabel="Добавить email"
          emptyTitle="Адресов нет"
        >
          {(item, index, patch) => (
            <div className={styles.grid2}>
              <TextField
                label="Адрес"
                path={`emails.${index}.email`}
                type="email"
                inputMode="email"
                required
                value={item.email}
                onChange={(email) => patch({ email })}
                placeholder="sales@oinau.kz"
              />
              <LocField
                label="Подпись"
                path={`emails.${index}.label`}
                kind="line"
                value={item.label}
                onChange={(label) => patch({ label })}
              />
            </div>
          )}
        </ListEditor>
      </Panel>

      <Panel
        title="WhatsApp"
        description="Кнопка чата на сайте. Пустой номер — кнопка не показывается."
        paths={['whatsapp']}
      >
        <GroupError path="whatsapp" />
        <div className={styles.grid2}>
          <TextField
            label="Номер WhatsApp"
            path="whatsapp.number"
            type="tel"
            inputMode="tel"
            value={form.whatsapp.number}
            onChange={(number) => set('whatsapp', { ...form.whatsapp, number })}
            placeholder="+7 701 000 00 00"
          />
          <LocField
            label="Текст сообщения"
            path="whatsapp.message"
            kind="short"
            rows={2}
            value={form.whatsapp.message}
            onChange={(message) => set('whatsapp', { ...form.whatsapp, message })}
            hint="Подставляется в чат при переходе по кнопке"
          />
        </div>
      </Panel>

      <Panel
        title="Адрес и часы работы"
        description="Выводятся на странице контактов и в подвале."
        paths={['address', 'working_hours']}
      >
        <div className={styles.grid2}>
          <LocField
            label="Адрес"
            path="address"
            kind="short"
            value={form.address}
            onChange={(address) => set('address', address)}
          />
          <LocField
            label="Часы работы"
            path="working_hours"
            kind="short"
            value={form.working_hours}
            onChange={(working_hours) => set('working_hours', working_hours)}
            placeholder={'Пн–Пт 9:00–18:00\nСб 10:00–15:00'}
          />
        </div>
      </Panel>

      <Panel
        title="Точка на карте"
        description="Координаты склада или офиса: ссылка «Открыть на карте» рядом с адресом. Код встраивания карты не нужен."
        paths={['map']}
        defaultOpen={false}
        summary={isBlank(form.map.latitude) && isBlank(form.map.longitude) ? 'Не задана' : 'Задана'}
      >
        <GroupError path="map" />
        <div className={styles.grid2}>
          <TextField
            label="Широта"
            path="map.latitude"
            inputMode="decimal"
            value={form.map.latitude}
            onChange={(latitude) => set('map', { ...form.map, latitude })}
            placeholder="43.238949"
            mono
          />
          <TextField
            label="Долгота"
            path="map.longitude"
            inputMode="decimal"
            value={form.map.longitude}
            onChange={(longitude) => set('map', { ...form.map, longitude })}
            placeholder="76.889709"
            mono
          />
        </div>
      </Panel>

      <SeoPanel value={form.seo} onChange={(seo) => set('seo', seo)} />
    </>
  );
}
