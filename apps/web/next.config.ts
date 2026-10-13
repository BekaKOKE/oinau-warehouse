import type { NextConfig } from 'next';

/**
 * `standalone` нужен только production-образу: без него он весит около
 * гигабайта. Собирать standalone локально нельзя по-другому — сборка
 * раскладывает зависимости символическими ссылками, а Windows без
 * режима разработчика их создавать не даёт, и `pnpm build` падает
 * с EPERM уже после успешной сборки страниц.
 *
 * Поэтому режим включается переменной, которую задаёт Dockerfile
 * (infra/docker/node.Dockerfile), а локальная сборка идёт обычной.
 */
const standalone = process.env.NEXT_BUILD_STANDALONE === '1';

/**
 * Изображения товаров раздаёт CDN (локально — MinIO), не Next.js и не
 * backend. Разрешать произвольные источники нельзя: оптимизатор Next
 * превратился бы в открытый прокси, через который качают что угодно
 * за наш счёт. Поэтому список хостов закрытый.
 *
 * Прод-домен берётся из `NEXT_PUBLIC_CDN_BASE_URL` (значение того же
 * `CDN_BASE_URL`, что задан backend). Переменная читается ТОЛЬКО здесь
 * и попадает в образ на этапе сборки: в standalone-сервере конфиг уже
 * зафиксирован, менять его переменной при запуске поздно.
 */
const cdnHost = (() => {
  const raw = process.env.NEXT_PUBLIC_CDN_BASE_URL;
  if (!raw) return null;
  try {
    const url = new URL(raw);
    return { protocol: url.protocol.replace(':', '') as 'http' | 'https', hostname: url.hostname };
  } catch {
    // Кривое значение не должно ронять сборку — остаются дефолтные хосты.
    return null;
  }
})();

const cdnPatterns = [
  { protocol: 'https' as const, hostname: 'cdn.oinau-pro.kz' },
  { protocol: 'http' as const, hostname: 'localhost' },
  { protocol: 'http' as const, hostname: '127.0.0.1' },
  { protocol: 'http' as const, hostname: 'minio' },
  ...(cdnHost ? [cdnHost] : []),
];

const config: NextConfig = {
  ...(standalone ? { output: 'standalone' as const } : {}),
  reactStrictMode: true,
  // Ссылки в письмах backend ведут на /account/…, а кабинет живёт
  // в /cabinet/…. Перенаправление сохраняет query с токеном; постоянным
  // его не делаем, чтобы браузер не закешировал адрес письма навсегда.
  async redirects() {
    return [
      { source: '/account/verify-email', destination: '/cabinet/verify-email', permanent: false },
      {
        source: '/account/reset-password',
        destination: '/cabinet/reset-password',
        permanent: false,
      },
    ];
  },
  poweredByHeader: false,
  images: {
    remotePatterns: cdnPatterns,
  },
};

export default config;
