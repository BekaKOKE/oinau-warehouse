/**
 * Метаданные страниц.
 *
 * Тексты берутся из CMS и каталога. Ничего не выдумывается: если у
 * товара нет своего SEO-описания, используется короткое описание из
 * карточки, а не сочинённая фраза.
 */

import type { Metadata } from 'next';

import type { Seo } from '@oinau/api-types';

import { SITE_NAME, SITE_TAGLINE, SITE_URL } from '@/lib/config';

export function absoluteUrl(path: string): string {
  return new URL(path, SITE_URL).toString();
}

/**
 * Добавляет бренд к заголовку страницы.
 *
 * Проверяется вхождение, а не окончание строки: заголовок из CMS часто
 * уже содержит название («OINAU PRO — комплектующие для площадок»),
 * и приписывать бренд второй раз незачем.
 */
export function titleWithBrand(title: string): string {
  return title.includes(SITE_NAME) ? title : `${title} — ${SITE_NAME}`;
}

export type PageSeoInput = {
  title: string;
  description?: string | null;
  path: string;
  image?: string | null;
  /** Страницы поиска и постраничная выдача индексации не подлежат. */
  noindex?: boolean;
};

export function buildMetadata({
  title,
  description,
  path,
  image,
  noindex,
}: PageSeoInput): Metadata {
  const url = absoluteUrl(path);
  const fullTitle = titleWithBrand(title);
  const text = description ?? SITE_TAGLINE;

  return {
    // `absolute` отключает шаблон из корневого макета: бренд к заголовку
    // добавляет titleWithBrand, и без этого он приписался бы дважды.
    title: { absolute: fullTitle },
    description: text,
    alternates: { canonical: url },
    robots: noindex ? { index: false, follow: true } : { index: true, follow: true },
    openGraph: {
      type: 'website',
      siteName: SITE_NAME,
      title: fullTitle,
      description: text,
      url,
      locale: 'ru_RU',
      ...(image ? { images: [{ url: image }] } : {}),
    },
    twitter: {
      card: image ? 'summary_large_image' : 'summary',
      title: fullTitle,
      description: text,
      ...(image ? { images: [image] } : {}),
    },
  };
}

/** Метаданные страницы CMS: своё значение раздела, иначе — общее. */
export function metadataFromSeo(seo: Seo | null | undefined, fallback: PageSeoInput): Metadata {
  return buildMetadata({
    ...fallback,
    title: seo?.title ?? seo?.og_title ?? fallback.title,
    description: seo?.description ?? seo?.og_description ?? fallback.description,
    image: seo?.og_image?.url ?? fallback.image,
  });
}
