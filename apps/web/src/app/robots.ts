import type { MetadataRoute } from 'next';

import { absoluteUrl } from '@/lib/seo';

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: '*',
      allow: '/',
      // Личные списки и кабинет клиента в индексе не нужны.
      disallow: ['/favorites', '/cabinet', '/account'],
    },
    sitemap: absoluteUrl('/sitemap.xml'),
  };
}
