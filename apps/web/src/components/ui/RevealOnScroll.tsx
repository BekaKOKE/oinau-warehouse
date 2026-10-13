/**
 * Появление блоков при прокрутке.
 *
 * Элементы помечаются атрибутом `data-reveal` в серверной разметке, а этот
 * компонент (один на страницу) следит за ними и ставит `data-revealed`,
 * когда блок входит в экран. Прячутся блоки только после того, как
 * компонент включился (`html[data-reveal-ready]`): без JavaScript и до
 * гидрации весь контент виден. То, что уже на экране, показывается сразу —
 * без мигания.
 */

'use client';

import { usePathname } from 'next/navigation';
import { useEffect } from 'react';

export function RevealOnScroll() {
  const pathname = usePathname();

  useEffect(() => {
    const root = document.documentElement;
    const reduce =
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduce || typeof IntersectionObserver === 'undefined') return;

    const elements = Array.from(
      document.querySelectorAll<HTMLElement>('[data-reveal]:not([data-revealed])'),
    );
    const viewport = window.innerHeight;
    for (const element of elements) {
      if (element.getBoundingClientRect().top < viewport) {
        element.setAttribute('data-revealed', '');
      }
    }

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          entry.target.setAttribute('data-revealed', '');
          observer.unobserve(entry.target);
        }
      },
      { rootMargin: '0px 0px -40px 0px', threshold: 0 },
    );
    elements
      .filter((element) => !element.hasAttribute('data-revealed'))
      .forEach((element) => observer.observe(element));
    root.setAttribute('data-reveal-ready', '');

    return () => observer.disconnect();
  }, [pathname]);

  return null;
}
