/**
 * Контакты (ContactsContent).
 *
 * Первый телефон и первый email — основные (их отдаёт публичный API настроек).
 * Карта хранится координатами, код встраивания (iframe) backend не принимает.
 */

import type { ContactsContent } from '@/lib/api/types';
import type { FieldErrors } from '@/lib/errors';

import {
  coordinateError,
  emailError,
  isBlank,
  isLocEmpty,
  locFrom,
  locOut,
  newUid,
  parseCoordinate,
  phoneError,
  validateLoc,
  type Loc,
} from './fields';
import type { SectionSpec } from './sections';
import { seoFromData, seoMedia, seoToPayload, validateSeo, type SeoForm } from './seo';

export const MAX_PHONES = 10;
export const MAX_EMAILS = 10;

export type PhoneForm = { uid: string; number: string; label: Loc };
export type EmailForm = { uid: string; email: string; label: Loc };

export type ContactsForm = {
  phones: PhoneForm[];
  emails: EmailForm[];
  whatsapp: { number: string; message: Loc };
  address: Loc;
  working_hours: Loc;
  map: { latitude: string; longitude: string };
  seo: SeoForm;
};

export function emptyPhone(): PhoneForm {
  return { uid: newUid(), number: '', label: {} };
}

export function emptyEmail(): EmailForm {
  return { uid: newUid(), email: '', label: {} };
}

function whatsappFilled(form: ContactsForm): boolean {
  return !isBlank(form.whatsapp.number) || !isLocEmpty(form.whatsapp.message);
}

function mapFilled(form: ContactsForm): boolean {
  return !isBlank(form.map.latitude) || !isBlank(form.map.longitude);
}

/** Номер в том виде, как его сохранит backend: пробелы схлопнуты. */
function displayPhone(value: string): string {
  return value.trim().replace(/\s+/g, ' ');
}

export const contactsSpec: SectionSpec<'contacts', ContactsForm> = {
  fromData: (data) => ({
    phones: (data.phones ?? []).map((item) => ({
      uid: newUid(),
      number: item.number,
      label: locFrom(item.label),
    })),
    emails: (data.emails ?? []).map((item) => ({
      uid: newUid(),
      email: item.email,
      label: locFrom(item.label),
    })),
    whatsapp: {
      number: data.whatsapp?.number ?? '',
      message: locFrom(data.whatsapp?.message),
    },
    address: locFrom(data.address),
    working_hours: locFrom(data.working_hours),
    map: {
      latitude: data.map ? String(data.map.latitude) : '',
      longitude: data.map ? String(data.map.longitude) : '',
    },
    seo: seoFromData(data.seo),
  }),

  toPayload: (form): ContactsContent => ({
    phones: form.phones.map((item) => ({
      number: displayPhone(item.number),
      label: locOut(item.label),
    })),
    emails: form.emails.map((item) => ({ email: item.email.trim(), label: locOut(item.label) })),
    whatsapp: whatsappFilled(form)
      ? { number: displayPhone(form.whatsapp.number), message: locOut(form.whatsapp.message) }
      : null,
    address: locOut(form.address),
    working_hours: locOut(form.working_hours),
    map: mapFilled(form)
      ? {
          latitude: parseCoordinate(form.map.latitude) ?? 0,
          longitude: parseCoordinate(form.map.longitude) ?? 0,
        }
      : null,
    seo: seoToPayload(form.seo),
  }),

  validate: (form) => {
    const errors: FieldErrors = {};
    if (form.phones.length > MAX_PHONES) errors.phones = `Не больше ${MAX_PHONES} телефонов`;
    form.phones.forEach((item, index) => {
      const error = phoneError(item.number);
      if (error) errors[`phones.${index}.number`] = error;
      validateLoc(errors, `phones.${index}.label`, item.label, 'line');
    });
    if (form.emails.length > MAX_EMAILS) errors.emails = `Не больше ${MAX_EMAILS} адресов`;
    form.emails.forEach((item, index) => {
      const error = emailError(item.email);
      if (error) errors[`emails.${index}.email`] = error;
      validateLoc(errors, `emails.${index}.label`, item.label, 'line');
    });
    if (whatsappFilled(form)) {
      const error = phoneError(form.whatsapp.number);
      if (error) errors['whatsapp.number'] = error;
      validateLoc(errors, 'whatsapp.message', form.whatsapp.message, 'short');
    }
    validateLoc(errors, 'address', form.address, 'short');
    validateLoc(errors, 'working_hours', form.working_hours, 'short');
    if (mapFilled(form)) {
      const latitude = isBlank(form.map.latitude)
        ? 'Укажите широту вместе с долготой'
        : coordinateError(form.map.latitude, 90);
      const longitude = isBlank(form.map.longitude)
        ? 'Укажите долготу вместе с широтой'
        : coordinateError(form.map.longitude, 180);
      if (latitude) errors['map.latitude'] = latitude;
      if (longitude) errors['map.longitude'] = longitude;
    }
    validateSeo(errors, form.seo);
    return errors;
  },

  media: (form) => seoMedia(form.seo),
};
