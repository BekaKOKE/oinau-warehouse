/**
 * Общая подготовка тестов админки.
 *
 * Заглушаются только части Next.js, которых нет в jsdom (навигация).
 * Собственный код тестируется как есть; сеть подменяется на уровне
 * `fetch` в самих тестах.
 */

import '@testing-library/jest-dom/vitest';

import { cleanup } from '@testing-library/react';
import React from 'react';
import { afterEach, beforeEach, vi } from 'vitest';

export const routerPush = vi.fn();
export const routerReplace = vi.fn();

export const navigationState = { pathname: '/', search: '' };

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
  useSearchParams: () => new URLSearchParams(navigationState.search),
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

beforeEach(() => {
  routerPush.mockClear();
  routerReplace.mockClear();
  navigationState.pathname = '/';
  navigationState.search = '';
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
