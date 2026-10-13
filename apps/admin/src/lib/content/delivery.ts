/** Доставка и оплата (DeliveryContent). */

import type { DeliveryContent } from '@/lib/api/types';
import type { FieldErrors } from '@/lib/errors';

import { locFrom, locOut, locRequired, newUid, validateLoc, type Loc } from './fields';
import type { SectionSpec } from './sections';
import { seoFromData, seoMedia, seoToPayload, validateSeo, type SeoForm } from './seo';

export const MAX_DELIVERY_METHODS = 20;

export type DeliveryMethodForm = { uid: string; title: Loc; text: Loc };

export type DeliveryForm = {
  intro: Loc;
  methods: DeliveryMethodForm[];
  payment: Loc;
  seo: SeoForm;
};

export function emptyDeliveryMethod(): DeliveryMethodForm {
  return { uid: newUid(), title: {}, text: {} };
}

export const deliverySpec: SectionSpec<'delivery', DeliveryForm> = {
  fromData: (data) => ({
    intro: locFrom(data.intro),
    methods: (data.methods ?? []).map((item) => ({
      uid: newUid(),
      title: locFrom(item.title),
      text: locFrom(item.text),
    })),
    payment: locFrom(data.payment),
    seo: seoFromData(data.seo),
  }),

  toPayload: (form): DeliveryContent => ({
    intro: locOut(form.intro),
    methods: form.methods.map((item) => ({
      title: locRequired(item.title),
      text: locOut(item.text),
    })),
    payment: locOut(form.payment),
    seo: seoToPayload(form.seo),
  }),

  validate: (form) => {
    const errors: FieldErrors = {};
    validateLoc(errors, 'intro', form.intro, 'text');
    if (form.methods.length > MAX_DELIVERY_METHODS) {
      errors.methods = `Не больше ${MAX_DELIVERY_METHODS} способов доставки`;
    }
    form.methods.forEach((item, index) => {
      validateLoc(errors, `methods.${index}.title`, item.title, 'line', { required: true });
      validateLoc(errors, `methods.${index}.text`, item.text, 'text');
    });
    validateLoc(errors, 'payment', form.payment, 'text');
    validateSeo(errors, form.seo);
    return errors;
  },

  media: (form) => seoMedia(form.seo),
};
