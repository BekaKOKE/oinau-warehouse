/**
 * Реквизиты (RequisitesContent). Все поля необязательны, но каждое
 * заполненное проверяется по формату РК — как на backend.
 */

import type { RequisitesContent } from '@/lib/api/types';
import type { FieldErrors } from '@/lib/errors';

import {
  bikError,
  binError,
  compactUpper,
  ibanError,
  isBlank,
  kbeError,
  locFrom,
  locOut,
  validateLoc,
  type Loc,
} from './fields';
import type { SectionSpec } from './sections';

export type RequisitesForm = {
  company_name: Loc;
  bin: string;
  iban: string;
  bank_name: Loc;
  bik: string;
  kbe: string;
  legal_address: Loc;
};

const CODES = [
  ['bin', binError],
  ['iban', ibanError],
  ['bik', bikError],
  ['kbe', kbeError],
] as const;

function code(value: string): string | null {
  return isBlank(value) ? null : compactUpper(value);
}

export const requisitesSpec: SectionSpec<'requisites', RequisitesForm> = {
  fromData: (data) => ({
    company_name: locFrom(data.company_name),
    bin: data.bin ?? '',
    iban: data.iban ?? '',
    bank_name: locFrom(data.bank_name),
    bik: data.bik ?? '',
    kbe: data.kbe ?? '',
    legal_address: locFrom(data.legal_address),
  }),

  toPayload: (form): RequisitesContent => ({
    company_name: locOut(form.company_name),
    bin: code(form.bin),
    iban: code(form.iban),
    bank_name: locOut(form.bank_name),
    bik: code(form.bik),
    kbe: code(form.kbe),
    legal_address: locOut(form.legal_address),
  }),

  validate: (form) => {
    const errors: FieldErrors = {};
    validateLoc(errors, 'company_name', form.company_name, 'line');
    validateLoc(errors, 'bank_name', form.bank_name, 'line');
    validateLoc(errors, 'legal_address', form.legal_address, 'short');
    for (const [field, check] of CODES) {
      if (isBlank(form[field])) continue;
      const error = check(form[field]);
      if (error) errors[field] = error;
    }
    return errors;
  },

  media: () => [],
};
