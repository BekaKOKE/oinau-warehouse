/**
 * Общие настройки сайта (SiteSettingsContent): название, SEO по умолчанию,
 * соцсети. Телефон, email и WhatsApp шапки берутся из раздела «Контакты» —
 * отдельных полей для них в настройках backend нет.
 */

import type { SiteSettingsContent, SocialNetwork } from '@/lib/api/types';
import type { FieldErrors } from '@/lib/errors';

import { httpsUrlError, locFrom, locOut, newUid, validateLoc, type Loc } from './fields';
import type { SectionSpec } from './sections';
import { seoFromData, seoMedia, seoToPayload, validateSeo, type SeoForm } from './seo';

export const MAX_SOCIAL_LINKS = 10;

export const SOCIAL_NETWORK_LABELS: Record<SocialNetwork, string> = {
  INSTAGRAM: 'Instagram',
  TELEGRAM: 'Telegram',
  WHATSAPP: 'WhatsApp',
  FACEBOOK: 'Facebook',
  YOUTUBE: 'YouTube',
  TIKTOK: 'TikTok',
  VK: 'VK',
};

export const SOCIAL_NETWORKS = Object.keys(SOCIAL_NETWORK_LABELS) as SocialNetwork[];

export function isSocialNetwork(value: string): value is SocialNetwork {
  return (SOCIAL_NETWORKS as string[]).includes(value);
}

export type SocialLinkForm = { uid: string; network: SocialNetwork | ''; url: string };

export type SettingsForm = {
  site_name: Loc;
  seo: SeoForm;
  social_links: SocialLinkForm[];
};

export function emptySocialLink(): SocialLinkForm {
  return { uid: newUid(), network: '', url: '' };
}

export const settingsSpec: SectionSpec<'settings', SettingsForm> = {
  fromData: (data) => ({
    site_name: locFrom(data.site_name),
    seo: seoFromData(data.seo),
    social_links: (data.social_links ?? []).map((item) => ({
      uid: newUid(),
      network: item.network,
      url: item.url,
    })),
  }),

  toPayload: (form): SiteSettingsContent => ({
    site_name: locOut(form.site_name),
    seo: seoToPayload(form.seo),
    // Строка без выбранной сети не пройдёт проверку формы и сюда не попадёт.
    social_links: form.social_links.flatMap((item) =>
      item.network ? [{ network: item.network, url: item.url.trim() }] : [],
    ),
  }),

  validate: (form) => {
    const errors: FieldErrors = {};
    validateLoc(errors, 'site_name', form.site_name, 'line');
    validateSeo(errors, form.seo);
    if (form.social_links.length > MAX_SOCIAL_LINKS) {
      errors.social_links = `Не больше ${MAX_SOCIAL_LINKS} ссылок`;
    }
    const seen = new Set<string>();
    form.social_links.forEach((item, index) => {
      if (!item.network) errors[`social_links.${index}.network`] = 'Выберите соцсеть';
      else if (seen.has(item.network)) {
        errors[`social_links.${index}.network`] = 'Каждая соцсеть указывается один раз';
      }
      if (item.network) seen.add(item.network);
      const error = httpsUrlError(item.url);
      if (error) errors[`social_links.${index}.url`] = error;
    });
    return errors;
  },

  media: (form) => seoMedia(form.seo),
};
