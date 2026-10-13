/** Услуги (ServicesContent): обжимка и обрезка канатов, металлорезка и т. п. */

import type { ServicesContent } from '@/lib/api/types';
import type { FieldErrors } from '@/lib/errors';

import {
  locFrom,
  locOut,
  locRequired,
  newUid,
  validateLoc,
  type Loc,
  type MediaRef,
} from './fields';
import type { SectionSpec } from './sections';
import { seoFromData, seoMedia, seoToPayload, validateSeo, type SeoForm } from './seo';

export const MAX_SERVICES = 30;
export const MAX_SERVICE_DETAILS = 20;
export const SERVICE_SLUG_RE = /^[a-z0-9-]+$/;

export type ServiceDetailForm = { uid: string; text: Loc };

export type ServiceForm = {
  uid: string;
  slug: string;
  title: Loc;
  summary: Loc;
  details: ServiceDetailForm[];
  priceNote: Loc;
  image: string | null;
  ctaLabel: Loc;
};

export type ServicesForm = {
  intro: Loc;
  items: ServiceForm[];
  seo: SeoForm;
};

export function emptyService(): ServiceForm {
  return {
    uid: newUid(),
    slug: '',
    title: {},
    summary: {},
    details: [],
    priceNote: {},
    image: null,
    ctaLabel: {},
  };
}

export function emptyServiceDetail(): ServiceDetailForm {
  return { uid: newUid(), text: {} };
}

/** Ошибка адреса услуги (якорь на странице /services#slug). */
export function serviceSlugError(value: string): string | null {
  if (!value.trim()) return 'Укажите адрес (slug)';
  if (value.length > 60) return 'Не длиннее 60 символов';
  if (!SERVICE_SLUG_RE.test(value)) return 'Строчная латиница, цифры и дефис';
  return null;
}

export const servicesSpec: SectionSpec<'services', ServicesForm> = {
  fromData: (data) => ({
    intro: locFrom(data.intro),
    items: (data.items ?? []).map((item) => ({
      uid: newUid(),
      slug: item.slug,
      title: locFrom(item.title),
      summary: locFrom(item.summary),
      details: (item.details ?? []).map((detail) => ({ uid: newUid(), text: locFrom(detail) })),
      priceNote: locFrom(item.price_note),
      image: item.image ?? null,
      ctaLabel: locFrom(item.cta_label),
    })),
    seo: seoFromData(data.seo),
  }),

  toPayload: (form): ServicesContent => ({
    intro: locOut(form.intro),
    items: form.items.map((item) => ({
      slug: item.slug.trim(),
      title: locRequired(item.title),
      summary: locOut(item.summary),
      details: item.details
        .map((detail) => locOut(detail.text))
        .filter((detail): detail is Record<string, string> => detail !== null),
      price_note: locOut(item.priceNote),
      image: item.image,
      cta_label: locOut(item.ctaLabel),
    })),
    seo: seoToPayload(form.seo),
  }),

  validate: (form) => {
    const errors: FieldErrors = {};
    validateLoc(errors, 'intro', form.intro, 'text');
    if (form.items.length > MAX_SERVICES) {
      errors.items = `Не больше ${MAX_SERVICES} услуг`;
    }
    const slugs = new Map<string, number>();
    form.items.forEach((item, index) => {
      const slugError = serviceSlugError(item.slug.trim());
      if (slugError) {
        errors[`items.${index}.slug`] = slugError;
      } else if (slugs.has(item.slug.trim())) {
        errors[`items.${index}.slug`] =
          `Такой адрес уже у услуги ${slugs.get(item.slug.trim())! + 1}`;
      }
      slugs.set(item.slug.trim(), index);
      validateLoc(errors, `items.${index}.title`, item.title, 'line', { required: true });
      validateLoc(errors, `items.${index}.summary`, item.summary, 'short');
      validateLoc(errors, `items.${index}.price_note`, item.priceNote, 'line');
      validateLoc(errors, `items.${index}.cta_label`, item.ctaLabel, 'line');
      if (item.details.length > MAX_SERVICE_DETAILS) {
        errors[`items.${index}.details`] = `Не больше ${MAX_SERVICE_DETAILS} пунктов`;
      }
      item.details.forEach((detail, detailIndex) => {
        validateLoc(errors, `items.${index}.details.${detailIndex}`, detail.text, 'line');
      });
    });
    validateSeo(errors, form.seo);
    return errors;
  },

  media: (form) => {
    const refs: MediaRef[] = form.items
      .map((item, index) =>
        item.image ? { path: `items.${index}.image`, uuid: item.image } : null,
      )
      .filter((ref): ref is MediaRef => ref !== null);
    return [...refs, ...seoMedia(form.seo)];
  },
};
