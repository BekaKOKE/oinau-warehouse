/**
 * FAQ (FaqContent). Отдельного поля порядка у вопроса нет: порядок на
 * сайте — порядок элементов в списке, он и сохраняется.
 */

import type { FaqContent } from '@/lib/api/types';
import type { FieldErrors } from '@/lib/errors';

import { locFrom, locRequired, newUid, validateLoc, type Loc } from './fields';
import type { SectionSpec } from './sections';
import { seoFromData, seoMedia, seoToPayload, validateSeo, type SeoForm } from './seo';

export const MAX_FAQ_ITEMS = 100;

export type FaqItemForm = { uid: string; question: Loc; answer: Loc };

export type FaqForm = { items: FaqItemForm[]; seo: SeoForm };

export function emptyFaqItem(): FaqItemForm {
  return { uid: newUid(), question: {}, answer: {} };
}

export const faqSpec: SectionSpec<'faq', FaqForm> = {
  fromData: (data) => ({
    items: (data.items ?? []).map((item) => ({
      uid: newUid(),
      question: locFrom(item.question),
      answer: locFrom(item.answer),
    })),
    seo: seoFromData(data.seo),
  }),

  toPayload: (form): FaqContent => ({
    items: form.items.map((item) => ({
      question: locRequired(item.question),
      answer: locRequired(item.answer),
    })),
    seo: seoToPayload(form.seo),
  }),

  validate: (form) => {
    const errors: FieldErrors = {};
    if (form.items.length > MAX_FAQ_ITEMS) errors.items = `Не больше ${MAX_FAQ_ITEMS} вопросов`;
    form.items.forEach((item, index) => {
      validateLoc(errors, `items.${index}.question`, item.question, 'question', {
        required: true,
      });
      validateLoc(errors, `items.${index}.answer`, item.answer, 'text', { required: true });
    });
    validateSeo(errors, form.seo);
    return errors;
  },

  media: (form) => seoMedia(form.seo),
};
