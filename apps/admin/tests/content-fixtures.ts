/**
 * Разделы CMS для тестов — формы из сгенерированных типов backend.
 */

import type {
  ContactsContent,
  ContentSectionData,
  ContentSectionKey,
  ContentSectionRead,
  ContentSectionSummary,
  DeliveryContent,
  FaqContent,
  HomeContent,
  MediaDetail,
  MediaRead,
  RequisitesContent,
  ServicesContent,
  SiteSettingsContent,
} from '@/lib/api/types';

export const CONTENT = '/api/v1/admin/content';
export const sectionUrl = (key: ContentSectionKey) => `${CONTENT}/${key}`;
export const MEDIA = '/api/v1/admin/media';
export const mediaUrl = (uuid: string) => `${MEDIA}/${uuid}`;

export const HERO_IMAGE = '11111111-1111-4111-8111-111111111111';
export const OG_IMAGE = '22222222-2222-4222-8222-222222222222';

/** Проверенный IBAN РК (контрольная сумма сходится). */
export const VALID_IBAN = 'KZ86125KZT5004100100';

const EMPTY_SEO = {
  title: null,
  description: null,
  og_title: null,
  og_description: null,
  og_image: null,
};

export const HOME: HomeContent = {
  hero: {
    title: { ru: 'Комплектующие для современных площадок' },
    subtitle: { ru: 'Канаты, крепёж и сиденья со склада в Алматы' },
    cta_label: { ru: 'Перейти в каталог' },
    cta_url: '/catalog',
    image: HERO_IMAGE,
  },
  advantages: [
    { title: { ru: 'Склад в Алматы' }, text: { ru: 'Отгрузка за 24 часа' } },
    { title: { ru: 'Сертификаты' }, text: null },
  ],
  about: { title: null, text: { ru: 'Поставляем комплектующие с 2015 года.' } },
  seo: { ...EMPTY_SEO, title: { ru: 'OINAU PRO — главная' }, og_image: OG_IMAGE },
};

export const CONTACTS: ContactsContent = {
  phones: [{ number: '+7 727 355 00 00', label: { ru: 'Отдел продаж' } }],
  emails: [{ email: 'sales@oinau.kz', label: null }],
  whatsapp: { number: '+7 701 555 00 00', message: { ru: 'Здравствуйте!' } },
  address: { ru: 'Алматы, ул. Складская, 1' },
  working_hours: { ru: 'Пн–Пт 9:00–18:00' },
  map: { latitude: 43.238949, longitude: 76.889709 },
  seo: EMPTY_SEO,
};

export const DELIVERY: DeliveryContent = {
  intro: { ru: 'Доставляем по всему Казахстану.' },
  methods: [
    { title: { ru: 'Самовывоз' }, text: { ru: 'Склад в Алматы' } },
    { title: { ru: 'Транспортная компания' }, text: null },
  ],
  payment: { ru: 'Безналичный расчёт' },
  seo: EMPTY_SEO,
};

export const FAQ: FaqContent = {
  items: [
    { question: { ru: 'Есть ли доставка?' }, answer: { ru: 'Да, по всему Казахстану.' } },
    { question: { ru: 'Работаете с ТОО?' }, answer: { ru: 'Да, по договору.' } },
  ],
  seo: EMPTY_SEO,
};

export const REQUISITES: RequisitesContent = {
  company_name: { ru: 'ТОО «OINAU PRO»' },
  bin: '123456789012',
  iban: VALID_IBAN,
  bank_name: { ru: 'АО «Народный банк»' },
  bik: 'HSBKKZKX',
  kbe: '17',
  legal_address: { ru: 'Алматы, ул. Складская, 1' },
};

export const SETTINGS: SiteSettingsContent = {
  site_name: { ru: 'OINAU PRO' },
  seo: { ...EMPTY_SEO, description: { ru: 'Комплектующие для площадок' } },
  social_links: [{ network: 'INSTAGRAM', url: 'https://instagram.com/oinau.pro' }],
};

export const SERVICES: ServicesContent = {
  intro: { ru: 'Готовим комплектующие под проект.' },
  items: [
    {
      slug: 'obzhimka-kanatov',
      title: { ru: 'Обжимка канатов' },
      summary: { ru: 'Опрессовка втулками.' },
      details: [{ ru: 'Алюминиевые втулки' }],
      price_note: { ru: 'По объёму партии' },
      image: null,
      cta_label: null,
    },
  ],
  seo: EMPTY_SEO,
};

export const SECTION_DATA: { [K in ContentSectionKey]: ContentSectionData<K> } = {
  home: HOME,
  contacts: CONTACTS,
  delivery: DELIVERY,
  faq: FAQ,
  requisites: REQUISITES,
  settings: SETTINGS,
  services: SERVICES,
};

export function makeRead<K extends ContentSectionKey>(
  key: K,
  data: ContentSectionData<K> = SECTION_DATA[key],
  overrides: Partial<ContentSectionRead<K>> = {},
): ContentSectionRead<K> {
  return {
    key,
    data,
    is_configured: true,
    updated_at: '2026-09-14T04:00:00Z',
    updated_by_id: 1,
    ...overrides,
  } as ContentSectionRead<K>;
}

export const SUMMARIES: ContentSectionSummary[] = [
  { key: 'home', is_configured: true, updated_at: '2026-09-14T04:00:00Z', updated_by_id: 1 },
  { key: 'contacts', is_configured: true, updated_at: '2026-09-13T10:30:00Z', updated_by_id: 1 },
  { key: 'delivery', is_configured: false, updated_at: null, updated_by_id: null },
  { key: 'faq', is_configured: true, updated_at: '2026-09-12T06:00:00Z', updated_by_id: 2 },
  { key: 'requisites', is_configured: false, updated_at: null, updated_by_id: null },
  { key: 'settings', is_configured: true, updated_at: '2026-09-11T08:00:00Z', updated_by_id: 1 },
  { key: 'services', is_configured: false, updated_at: null, updated_by_id: null },
];

export function makeMedia(overrides: Partial<MediaDetail> = {}): MediaDetail {
  const uuid = overrides.uuid ?? OG_IMAGE;
  return {
    uuid,
    status: 'READY',
    original_filename: 'og-cover.png',
    content_type: 'image/png',
    size_bytes: 20480,
    width: 1200,
    height: 630,
    url: `http://cdn.test/content/${uuid}/variants/large.webp`,
    variants: {
      thumb: `http://cdn.test/content/${uuid}/variants/thumb.webp`,
      large: `http://cdn.test/content/${uuid}/variants/large.webp`,
    },
    failure_reason: null,
    usage_count: 0,
    uploaded_by_id: 1,
    created_at: '2026-09-14T04:00:00Z',
    updated_at: '2026-09-14T04:00:00Z',
    products: [],
    content_sections: ['home'],
    ...overrides,
  };
}

export function mediaRow(overrides: Partial<MediaRead> = {}): MediaRead {
  const { products: _products, content_sections: _sections, ...row } = makeMedia(overrides);
  return row;
}
