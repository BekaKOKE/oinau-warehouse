/**
 * Плавающая кнопка WhatsApp.
 *
 * Ссылку формирует backend (CMS готовит `wa.me` с текстом сообщения).
 * Номер в компоненте не хардкодится: запасное значение приходит из
 * переменной окружения на случай незаполненной CMS.
 *
 * Кнопка фиксирована в углу экрана, поэтому при прокрутке неизбежно
 * проезжает над содержимым. Чтобы она не закрывала «В заявку», поля
 * формы и ссылки, при прокрутке (и фоново раз в 300 мс) проверяется, что лежит под ней:
 * если там интерактивный элемент, кнопка временно прячется и не ловит
 * нажатия. Пока в поле формы стоит курсор (на телефоне открыта
 * клавиатура), кнопка тоже скрыта.
 */

'use client';

import { useEffect, useRef, useState } from 'react';

import { WHATSAPP_MESSAGE, WHATSAPP_NUMBER, whatsappLink } from '@/lib/config';
import styles from './WhatsAppButton.module.css';

const INTERACTIVE = 'a[href], button, input, select, textarea, summary, label, [role="button"]';
const FORM_FIELD = 'input, select, textarea';

/**
 * Лежит ли под кнопкой что-то нажимаемое.
 *
 * Проверяется сетка 5×5 по прямоугольнику кнопки с запасом в 6 px:
 * край ссылки или кнопки может задевать круг между редкими точками,
 * а вплотную к краю нажимаемого элемента кнопка тоже мешает пальцу.
 */
export function overlapsInteractive(button: HTMLElement): boolean {
  if (typeof document.elementsFromPoint !== 'function') return false;
  const rect = button.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return false;

  const margin = 6;
  const left = rect.left - margin;
  const top = rect.top - margin;
  const size = [rect.width + margin * 2, rect.height + margin * 2] as const;

  for (let row = 0; row < 5; row += 1) {
    for (let column = 0; column < 5; column += 1) {
      const x = left + (size[0] * column) / 4;
      const y = top + (size[1] * row) / 4;
      const hit = document
        .elementsFromPoint(x, y)
        .some((element) => !button.contains(element) && element.closest(INTERACTIVE) !== null);
      if (hit) return true;
    }
  }
  return false;
}

export function WhatsAppButton({ url }: { url?: string | null }) {
  const href = url || whatsappLink(WHATSAPP_NUMBER, WHATSAPP_MESSAGE);
  const ref = useRef<HTMLAnchorElement>(null);
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    // Флаг ставится до запроса кадра: колбэк может выполниться раньше,
    // чем вернётся идентификатор, и проверка не должна «залипнуть».
    let pending = false;
    let frame = 0;

    function update() {
      pending = false;
      const button = ref.current;
      if (!button) return;
      // Сфокусированная с клавиатуры кнопка не прячется из-под курсора.
      if (document.activeElement === button) {
        setHidden(false);
        return;
      }
      const typing = document.activeElement?.matches(FORM_FIELD) ?? false;
      setHidden(typing || overlapsInteractive(button));
    }

    function schedule() {
      if (pending) return;
      pending = true;
      frame = window.requestAnimationFrame(update);
    }

    schedule();
    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule);
    document.addEventListener('focusin', schedule);
    document.addEventListener('focusout', schedule);
    // Содержимое под кнопкой меняется и без прокрутки: догружаются
    // изображения, раскрываются вопросы, появляется «Добавлено ✓».
    // Редкая фоновая проверка ловит такие сдвиги; на скрытой вкладке молчит.
    const interval = window.setInterval(() => {
      if (document.visibilityState === 'visible') schedule();
    }, 300);
    return () => {
      window.clearInterval(interval);
      window.cancelAnimationFrame(frame);
      window.removeEventListener('scroll', schedule);
      window.removeEventListener('resize', schedule);
      document.removeEventListener('focusin', schedule);
      document.removeEventListener('focusout', schedule);
    };
  }, []);

  return (
    <a
      ref={ref}
      className={hidden ? `${styles.button} ${styles.hidden}` : styles.button}
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      aria-label="Написать в WhatsApp"
      data-hidden={hidden ? 'true' : undefined}
    >
      <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M12.04 2C6.58 2 2.13 6.45 2.13 11.91c0 1.75.46 3.46 1.32 4.97L2 22l5.25-1.38a9.87 9.87 0 0 0 4.79 1.22h.01c5.46 0 9.91-4.45 9.91-9.91 0-2.65-1.03-5.14-2.9-7.01A9.82 9.82 0 0 0 12.04 2Zm0 18.15h-.01a8.2 8.2 0 0 1-4.19-1.15l-.3-.18-3.12.82.83-3.04-.2-.31a8.17 8.17 0 0 1-1.26-4.38c0-4.54 3.7-8.23 8.25-8.23 2.2 0 4.27.86 5.83 2.41a8.19 8.19 0 0 1 2.41 5.83c0 4.54-3.7 8.23-8.24 8.23Zm4.52-6.16c-.25-.12-1.47-.72-1.69-.81-.23-.08-.39-.12-.56.13-.16.24-.64.8-.79.97-.14.16-.29.18-.54.06-.25-.12-1.05-.39-1.99-1.23-.74-.65-1.23-1.46-1.38-1.71-.14-.25-.01-.38.11-.5.11-.11.25-.29.37-.43.13-.15.17-.25.25-.41.08-.17.04-.31-.02-.43-.06-.12-.56-1.35-.76-1.84-.2-.48-.4-.42-.56-.43h-.47c-.16 0-.43.06-.65.31-.22.25-.86.84-.86 2.05s.88 2.38 1 2.54c.12.17 1.73 2.65 4.2 3.71.59.25 1.04.4 1.4.52.59.19 1.12.16 1.55.1.47-.07 1.47-.6 1.67-1.18.21-.58.21-1.07.15-1.18-.06-.1-.23-.17-.48-.29Z" />
      </svg>
    </a>
  );
}
