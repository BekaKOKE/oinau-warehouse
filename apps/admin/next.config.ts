import type { NextConfig } from 'next';

/**
 * `standalone` нужен только production-образу: без него он весит около
 * гигабайта. Локально этот режим не собирается — раскладка зависимостей
 * идёт символическими ссылками, а Windows без режима разработчика их
 * создавать не даёт. Переменную задаёт infra/docker/node.Dockerfile.
 */
const standalone = process.env.NEXT_BUILD_STANDALONE === '1';

const config: NextConfig = {
  ...(standalone ? { output: 'standalone' as const } : {}),
  /**
   * Все маршруты админки живут под /admin (/admin/login, /admin/products).
   * Префикс не зависит от домена: admin.oinau-pro.kz/admin и схема
   * «один домен, прокси по пути» работают без перенастройки, а статика
   * (/admin/_next) не пересекается со статикой витрины.
   */
  basePath: '/admin',
  reactStrictMode: true,
  poweredByHeader: false,
  async redirects() {
    return [{ source: '/', destination: '/admin', basePath: false, permanent: false }];
  },
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          // Админку нельзя встраивать во фреймы: защита от clickjacking.
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'Referrer-Policy', value: 'same-origin' },
          { key: 'X-Robots-Tag', value: 'noindex, nofollow' },
        ],
      },
    ];
  },
};

export default config;
