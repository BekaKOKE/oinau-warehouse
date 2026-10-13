import type { MetadataRoute } from 'next';

import { absoluteUrl } from '@/lib/seo';

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: '*',
      allow: '/',
      // Личные списки и заглушка кабинета в индексе не нужны.
      disallow: ['/favorites', '/cabinet'],
    },
    sitemap: absoluteUrl('/sitemap.xml'),
  };
}
