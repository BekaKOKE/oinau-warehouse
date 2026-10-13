/**
 * Главная (HomeContent): hero, преимущества, «О компании», SEO.
 *
 * Блок hero или «О компании» существует, только если в нём что-то
 * заполнено: пустой блок уходит как `null`, и витрина показывает свои
 * тексты по умолчанию, а не пустоту.
 */

import type { HomeContent } from '@/lib/api/types';
import type { FieldErrors } from '@/lib/errors';

import {
  isBlank,
  isLocEmpty,
  linkError,
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

export const MAX_ADVANTAGES = 12;

export type HeroForm = {
  title: Loc;
  subtitle: Loc;
  cta_label: Loc;
  cta_url: string;
  image: string | null;
};

export type AdvantageForm = { uid: string; title: Loc; text: Loc };

export type HomeForm = {
  hero: HeroForm;
  advantages: AdvantageForm[];
  about: { title: Loc; text: Loc };
  seo: SeoForm;
};

/**
 * Как витрина выделит заголовок: акцент — предпоследнее слово
 * (apps/web, Hero.splitTitle). Показываем, чтобы правка текста не
 * стала сюрпризом для утверждённого дизайна первого экрана.
 */
export function splitHeroTitle(title: string): { head: string; accent: string; tail: string } {
  const words = title.trim().split(/\s+/).filter(Boolean);
  if (words.length < 3) return { head: words.join(' '), accent: '', tail: '' };
  return {
    head: words.slice(0, -2).join(' '),
    accent: words[words.length - 2] ?? '',
    tail: words[words.length - 1] ?? '',
  };
}

export function emptyAdvantage(): AdvantageForm {
  return { uid: newUid(), title: {}, text: {} };
}

function heroFilled(hero: HeroForm): boolean {
  return (
    !isLocEmpty(hero.title) ||
    !isLocEmpty(hero.subtitle) ||
    !isLocEmpty(hero.cta_label) ||
    !isBlank(hero.cta_url) ||
    hero.image !== null
  );
}

function aboutFilled(about: HomeForm['about']): boolean {
  return !isLocEmpty(about.title) || !isLocEmpty(about.text);
}

export const homeSpec: SectionSpec<'home', HomeForm> = {
  fromData: (data) => ({
    hero: {
      title: locFrom(data.hero?.title),
      subtitle: locFrom(data.hero?.subtitle),
      cta_label: locFrom(data.hero?.cta_label),
      cta_url: data.hero?.cta_url ?? '',
      image: data.hero?.image ?? null,
    },
    advantages: (data.advantages ?? []).map((item) => ({
      uid: newUid(),
      title: locFrom(item.title),
      text: locFrom(item.text),
    })),
    about: { title: locFrom(data.about?.title), text: locFrom(data.about?.text) },
    seo: seoFromData(data.seo),
  }),

  toPayload: (form): HomeContent => ({
    hero: heroFilled(form.hero)
      ? {
          title: locRequired(form.hero.title),
          subtitle: locOut(form.hero.subtitle),
          cta_label: locOut(form.hero.cta_label),
          cta_url: form.hero.cta_url.trim() || null,
          image: form.hero.image,
        }
      : null,
    advantages: form.advantages.map((item) => ({
      title: locRequired(item.title),
      text: locOut(item.text),
    })),
    about: aboutFilled(form.about)
      ? { title: locOut(form.about.title), text: locRequired(form.about.text) }
      : null,
    seo: seoToPayload(form.seo),
  }),

  validate: (form) => {
    const errors: FieldErrors = {};
    const { hero, about } = form;
    if (heroFilled(hero)) {
      validateLoc(errors, 'hero.title', hero.title, 'line', { required: true });
      validateLoc(errors, 'hero.subtitle', hero.subtitle, 'short');
      validateLoc(errors, 'hero.cta_label', hero.cta_label, 'line');
      const hasLabel = !isLocEmpty(hero.cta_label);
      const hasUrl = !isBlank(hero.cta_url);
      if (hasUrl) {
        const error = linkError(hero.cta_url);
        if (error) errors['hero.cta_url'] = error;
      }
      if (hasLabel !== hasUrl) {
        errors[hasLabel ? 'hero.cta_url' : 'hero.cta_label'] ??=
          'Текст и ссылка кнопки задаются вместе';
      }
    }
    if (form.advantages.length > MAX_ADVANTAGES) {
      errors.advantages = `Не больше ${MAX_ADVANTAGES} преимуществ`;
    }
    form.advantages.forEach((item, index) => {
      validateLoc(errors, `advantages.${index}.title`, item.title, 'line', { required: true });
      validateLoc(errors, `advantages.${index}.text`, item.text, 'short');
    });
    if (aboutFilled(about)) {
      validateLoc(errors, 'about.title', about.title, 'line');
      validateLoc(errors, 'about.text', about.text, 'text', { required: true });
    }
    validateSeo(errors, form.seo);
    return errors;
  },

  media: (form) => {
    const refs: MediaRef[] = [];
    if (form.hero.image) refs.push({ path: 'hero.image', uuid: form.hero.image });
    return [...refs, ...seoMedia(form.seo)];
  },
};
