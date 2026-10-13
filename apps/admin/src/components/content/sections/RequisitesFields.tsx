'use client';

import type { RequisitesForm } from '@/lib/content/requisites';

import { LocField, TextField } from '../fields';
import { Panel } from '../FormContext';
import type { FieldsProps } from '../SectionEditor';
import styles from '../Content.module.css';

export function RequisitesFields({ form, update }: FieldsProps<RequisitesForm>) {
  const set = <F extends keyof RequisitesForm>(field: F, value: RequisitesForm[F]) =>
    update((current) => ({ ...current, [field]: value }));

  return (
    <>
      <Panel
        title="Компания"
        description="Наименование и юридический адрес. Незаполненные реквизиты на сайте не выводятся."
        paths={['company_name', 'legal_address']}
      >
        <LocField
          label="Наименование"
          path="company_name"
          kind="line"
          value={form.company_name}
          onChange={(value) => set('company_name', value)}
          placeholder="ТОО «OINAU PRO»"
        />
        <LocField
          label="Юридический адрес"
          path="legal_address"
          kind="short"
          rows={2}
          value={form.legal_address}
          onChange={(value) => set('legal_address', value)}
        />
      </Panel>

      <Panel
        title="Банковские реквизиты"
        description="Проверяются по формату РК; IBAN — с контрольной суммой."
        paths={['bin', 'iban', 'bank_name', 'bik', 'kbe']}
      >
        <div className={styles.grid2}>
          <TextField
            label="БИН / ИИН"
            path="bin"
            inputMode="numeric"
            value={form.bin}
            onChange={(value) => set('bin', value)}
            placeholder="12 цифр"
            mono
          />
          <TextField
            label="IBAN"
            path="iban"
            value={form.iban}
            onChange={(value) => set('iban', value)}
            placeholder="KZ00 0000 0000 0000 0000"
            hint="Пробелы можно не убирать"
            mono
          />
          <LocField
            label="Банк"
            path="bank_name"
            kind="line"
            value={form.bank_name}
            onChange={(value) => set('bank_name', value)}
          />
          <TextField
            label="БИК"
            path="bik"
            value={form.bik}
            onChange={(value) => set('bik', value)}
            placeholder="HSBKKZKX"
            mono
          />
          <TextField
            label="КБе"
            path="kbe"
            inputMode="numeric"
            value={form.kbe}
            onChange={(value) => set('kbe', value)}
            placeholder="17"
            mono
          />
        </div>
      </Panel>
    </>
  );
}
