/**
 * Набор иконок админки — встроенный SVG, 20×20, обводка 1.6.
 *
 * Своя маленькая коллекция вместо пакета на тысячу иконок: нужно
 * два десятка, а единый стиль линий держится в одном файле.
 */

import type { SVGProps } from 'react';

const PATHS = {
  dashboard: 'M3 3h6v8H3zM11 3h6v5h-6zM11 10h6v7h-6zM3 13h6v4H3z',
  products: 'M3.5 6.5 10 3l6.5 3.5v7L10 17l-6.5-3.5zM3.5 6.5 10 10l6.5-3.5M10 10v7',
  categories: 'M3 4h5v5H3zM12 4h5v5h-5zM3 11h5v5H3zM12 13.5h5M14.5 11v5',
  attributes: 'M4 5h12M4 10h12M4 15h7M14 13l1.5 1.5L18 12',
  requests: 'M5 3h7l3 3v11H5zM12 3v3h3M8 10h5M8 13h5',
  stock: 'M2.5 8 10 4l7.5 4v9h-15zM6 17v-6h8v6M6 14h8',
  content: 'M4 3h12v14H4zM7 7h6M7 10h6M7 13h3',
  import: 'M10 3v9M6.5 8.5 10 12l3.5-3.5M4 14v3h12v-3',
  users:
    'M7.5 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM2.5 17c0-2.8 2.2-5 5-5s5 2.2 5 5M13 4.2a3 3 0 0 1 0 5.6M15 12.4c1.5.8 2.5 2.4 2.5 4.6',
  audit: 'M10 17a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM10 6v4l2.5 2.5',
  search: 'M9 15A6 6 0 1 0 9 3a6 6 0 0 0 0 12zM13.5 13.5 17 17',
  plus: 'M10 4v12M4 10h12',
  close: 'M5 5l10 10M15 5 5 15',
  check: 'M4 10.5 8 14.5 16 6',
  chevronDown: 'M5.5 8 10 12.5 14.5 8',
  chevronUp: 'M5.5 12 10 7.5 14.5 12',
  chevronLeft: 'M12 5 7 10l5 5',
  chevronRight: 'M8 5l5 5-5 5',
  menu: 'M3 5.5h14M3 10h14M3 14.5h14',
  logout: 'M8 3H4v14h4M13 6l4 4-4 4M17 10H8',
  alert: 'M10 3 2 17h16zM10 8v4M10 14.5v.5',
  info: 'M10 17a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM10 9v5M10 6.5v.5',
  lock: 'M5 9h10v8H5zM7 9V6.5a3 3 0 0 1 6 0V9',
  refresh: 'M16 10a6 6 0 1 1-1.8-4.3M16 3.5v3.5h-3.5',
  external: 'M11 3h6v6M17 3l-8 8M14 12v5H3V6h5',
  trash: 'M4 6h12M8 6V4h4v2M5.5 6l.8 11h7.4l.8-11',
  edit: 'M13.5 3.5 16.5 6.5 7 16H4v-3z',
  empty: 'M3 12h4l1.5 2.5h3L13 12h4M3 12l2.5-7h9l2.5 7v5H3z',
  arrowRight: 'M4 10h12M11 5l5 5-5 5',
  image: 'M3 4h14v12H3zM3 13l4-4 3 3 2-2 5 5M13 7.5h.01',
  tag: 'M3 3h7l7 7-7 7-7-7zM7 7h.01',
  integration:
    'M6 4.5h8v4H6zM6 11.5h8v4H6zM10 8.5v3M3.5 6.5h2.5M14 6.5h2.5M3.5 13.5h2.5M14 13.5h2.5',
} as const;

export type IconName = keyof typeof PATHS;

type IconProps = Omit<SVGProps<SVGSVGElement>, 'name'> & { name: IconName; size?: number };

export function Icon({ name, size = 18, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
