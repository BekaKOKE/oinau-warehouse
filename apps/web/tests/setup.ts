/**
 * Общая подготовка тестов витрины.
 *
 * Здесь заглушаются только те части Next.js, которых нет в jsdom:
 * навигация и оптимизация изображений. Всё остальное тестируется
 * как есть — подменять собственный код ради прохождения тестов
 * бессмысленно.
 */

import '@testing-library/jest-dom/vitest';

import { cleanup } from '@testing-library/react';
import React from 'react';
import { afterEach, beforeEach, vi } from 'vitest';

export const routerPush = vi.fn();
export const routerReplace = vi.fn();

/** Текущий маршрут для `usePathname`: тесты шапки меняют его сами. */
export const navigationState = { pathname: '/' };

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: routerPush,
    replace: routerReplace,
    prefetch: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
  }),
  usePathname: () => navigationState.pathname,
  useSearchParams: () => new URLSearchParams(),
  notFound: () => {
    throw new Error('NEXT_NOT_FOUND');
  },
}));

vi.mock('next/link', () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
  } & React.AnchorHTMLAttributes<HTMLAnchorElement>) =>
    React.createElement('a', { href, ...rest }, children),
}));

vi.mock('next/image', () => ({
  default: ({
    src,
    alt,
    fill: _fill,
    priority: _priority,
    ...rest
  }: {
    src: string;
    alt: string;
    fill?: boolean;
    priority?: boolean;
  } & React.ImgHTMLAttributes<HTMLImageElement>) =>
    React.createElement('img', { src, alt, ...rest }),
}));

beforeEach(() => {
  routerPush.mockClear();
  routerReplace.mockClear();
  navigationState.pathname = '/';
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
