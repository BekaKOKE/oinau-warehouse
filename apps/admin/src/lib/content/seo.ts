/**
 * SEO страницы (SeoMeta) — общий блок всех разделов, кроме реквизитов.
 *
 * Пустое поле на странице backend заменяет значением из «Настроек»,
 * поэтому все поля необязательны.
 */

import type { SeoMeta } from '@/lib/api/types';
import type { FieldErrors } from '@/lib/errors';

import { locFrom, locOut, validateLoc, type Loc, type MediaRef } from './fields';

export type SeoForm = {
  title: Loc;
  description: Loc;
  og_title: Loc;
  og_description: Loc;
  og_image: string | null;
};

export function seoFromData(seo: SeoMeta | undefined): SeoForm {
  return {
    title: locFrom(seo?.title),
    description: locFrom(seo?.description),
    og_title: locFrom(seo?.og_title),
    og_description: locFrom(seo?.og_description),
    og_image: seo?.og_image ?? null,
  };
}

export function seoToPayload(form: SeoForm): SeoMeta {
  return {
    title: locOut(form.title),
    description: locOut(form.description),
    og_title: locOut(form.og_title),
    og_description: locOut(form.og_description),
    og_image: form.og_image,
  };
}

export function validateSeo(errors: FieldErrors, form: SeoForm, prefix = 'seo'): void {
  validateLoc(errors, `${prefix}.title`, form.title, 'line');
  validateLoc(errors, `${prefix}.description`, form.description, 'seo');
  validateLoc(errors, `${prefix}.og_title`, form.og_title, 'line');
  validateLoc(errors, `${prefix}.og_description`, form.og_description, 'seo');
}

export function seoMedia(form: SeoForm, prefix = 'seo'): MediaRef[] {
  return form.og_image ? [{ path: `${prefix}.og_image`, uuid: form.og_image }] : [];
}
