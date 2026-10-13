/**
 * Логотип OINAU PRO — тот же файл, что на сайте.
 *
 * Обычный `<img>`, а не next/image: картинка статичная и маленькая, а
 * next/image под basePath требует префикс в src вручную — так он хотя бы
 * виден явно.
 */

import { BASE_PATH } from '@/lib/config';

export function BrandLogo({
  tone = 'color',
  height = 28,
  className,
}: {
  tone?: 'color' | 'white';
  height?: number;
  className?: string;
}) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={`${BASE_PATH}/brand/${tone === 'white' ? 'logo-white' : 'logo'}.png`}
      alt="OINAU PRO"
      width={Math.round((height * 1000) / 255)}
      height={height}
      className={className}
      style={{ display: 'block', width: 'auto', height }}
    />
  );
}
