/**
 * Разделы CMS — фиксированный набор backend (ContentSectionKey).
 *
 * Новых разделов фронтенд не придумывает: `Record<ContentSectionKey, …>`
 * ломает компиляцию, если в backend появится ключ без описания здесь.
 */

import type { ContentSectionData, ContentSectionKey } from '@/lib/api/types';
import type { FieldErrors } from '@/lib/errors';

import type { MediaRef } from './fields';

export type SectionMeta = {
  key: ContentSectionKey;
  label: string;
  description: string;
  /** Страница витрины, где виден раздел. */
  sitePath: string;
  siteLabel: string;
};

const META: Record<ContentSectionKey, Omit<SectionMeta, 'key'>> = {
  home: {
    label: 'Главная',
    description: 'Первый экран, преимущества, блок «О компании» и SEO главной.',
    sitePath: '/',
    siteLabel: 'Открыть главную',
  },
  contacts: {
    label: 'Контакты',
    description: 'Телефоны, email, WhatsApp, адрес, часы работы и точка на карте.',
    sitePath: '/contacts',
    siteLabel: 'Открыть страницу',
  },
  delivery: {
    label: 'Доставка',
    description: 'Вступление, способы доставки и условия оплаты.',
    sitePath: '/delivery',
    siteLabel: 'Открыть страницу',
  },
  faq: {
    label: 'FAQ',
    description: 'Частые вопросы и ответы. Порядок на сайте — как в списке.',
    sitePath: '/faq',
    siteLabel: 'Открыть страницу',
  },
  requisites: {
    label: 'Реквизиты',
    description: 'Юридические данные компании. Выводятся на странице контактов и в подвале.',
    sitePath: '/contacts#requisites',
    siteLabel: 'Открыть страницу',
  },
  services: {
    label: 'Услуги',
    description: 'Услуги компании: обжимка и обрезка канатов, металлорезка и другие работы.',
    sitePath: '/services',
    siteLabel: 'Открыть страницу',
  },
  settings: {
    label: 'Настройки',
    description: 'Название сайта, SEO по умолчанию и ссылки на соцсети.',
    sitePath: '/',
    siteLabel: 'Открыть сайт',
  },
};

/** Порядок разделов в навигации — порядок backend. */
const ORDER: readonly ContentSectionKey[] = [
  'home',
  'contacts',
  'delivery',
  'faq',
  'requisites',
  'settings',
  'services',
];

export const CONTENT_SECTIONS: readonly SectionMeta[] = ORDER.map((key) => ({
  key,
  ...META[key],
}));

export function isSectionKey(value: string): value is ContentSectionKey {
  return (ORDER as readonly string[]).includes(value);
}

export function sectionMeta(key: ContentSectionKey): SectionMeta {
  return { key, ...META[key] };
}

export function sectionSiteUrl(siteUrl: string, key: ContentSectionKey): string {
  return `${siteUrl.replace(/\/+$/, '')}${META[key].sitePath}`;
}

/** Форма раздела: разбор ответа, проверка и сборка тела PUT строго по схеме. */
export type SectionSpec<K extends ContentSectionKey, Form> = {
  fromData: (data: ContentSectionData<K>) => Form;
  toPayload: (form: Form) => ContentSectionData<K>;
  validate: (form: Form) => FieldErrors;
  /** Ссылки на медиатеку — чтобы 404/409 по UUID показать у нужного поля. */
  media: (form: Form) => MediaRef[];
};
