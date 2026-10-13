'use client';

/**
 * Защита несохранённой формы от ухода со страницы.
 *
 *  * закрытие и перезагрузка вкладки — `beforeunload` (useUnsavedGuard);
 *  * клик по внутренней ссылке (меню, хлебные крошки) — перехват в фазе
 *    захвата до обработчика next/link, подтверждение и переход роутером;
 *  * переходы, которые делает сам экран, — через возвращаемую функцию.
 *
 * Кнопку «Назад» браузера App Router отменять не позволяет: история уже
 * сменилась к моменту события.
 */

import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useRef } from 'react';

import { useConfirm } from '@/components/ui/Dialog';
import { BASE_PATH } from '@/lib/config';

import { useUnsavedGuard } from './useUnsavedGuard';

/** Путь приложения без basePath: next/link отдаёт в DOM `/admin/...`. */
export function stripBasePath(pathname: string): string {
  if (pathname === BASE_PATH) return '/';
  return pathname.startsWith(`${BASE_PATH}/`) ? pathname.slice(BASE_PATH.length) : pathname;
}

function internalTarget(event: MouseEvent): string | null {
  if (event.defaultPrevented || event.button !== 0) return null;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return null;
  const target = event.target instanceof Element ? event.target : null;
  const anchor = target?.closest('a[href]');
  if (!(anchor instanceof HTMLAnchorElement)) return null;
  if ((anchor.target && anchor.target !== '_self') || anchor.hasAttribute('download')) return null;

  const url = new URL(anchor.href, window.location.href);
  if (url.origin !== window.location.origin) return null;
  const here = window.location;
  // Якорь на той же странице никуда не уводит.
  if (url.pathname === here.pathname && url.search === here.search) return null;
  return `${stripBasePath(url.pathname)}${url.search}${url.hash}`;
}

export function useLeaveGuard(dirty: boolean): () => Promise<boolean> {
  const confirm = useConfirm();
  const router = useRouter();
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;

  useUnsavedGuard(dirty);

  const confirmLeave = useCallback(async () => {
    if (!dirtyRef.current) return true;
    return confirm({
      title: 'Уйти без сохранения?',
      description: 'В разделе есть несохранённые изменения. Они будут потеряны.',
      confirmLabel: 'Не сохранять',
      cancelLabel: 'Остаться',
    });
  }, [confirm]);

  useEffect(() => {
    if (!dirty) return;
    const onClick = (event: MouseEvent) => {
      const path = internalTarget(event);
      if (path === null) return;
      event.preventDefault();
      event.stopPropagation();
      void confirmLeave().then((leave) => {
        if (!leave) return;
        dirtyRef.current = false;
        router.push(path);
      });
    };
    document.addEventListener('click', onClick, true);
    return () => document.removeEventListener('click', onClick, true);
  }, [dirty, confirmLeave, router]);

  return confirmLeave;
}
