/**
 * Панель заявки.
 *
 * Модальная панель: пока она открыта, фокус остаётся внутри, Esc
 * закрывает, а фон не прокручивается. Без этого панель непроходима
 * с клавиатуры и «протекает» на страницу под собой.
 */

'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import type { RequestCreated } from '@oinau/api-types';

import { Button, ButtonLink } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/States';
import { formatAmount, formatQuantity, unitLabel } from '@/lib/format';
import { RequestForm } from './RequestForm';
import { RequestLines } from './RequestLines';
import { useRequestDrawer } from './RequestDrawerContext';
import { useRequest } from './RequestProvider';
import styles from './RequestDrawer.module.css';

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function SubmittedView({ result, onClose }: { result: RequestCreated; onClose: () => void }) {
  return (
    <div className={styles.success}>
      <div className={styles.successMark} aria-hidden="true">
        ✓
      </div>
      <h3 className={styles.formTitle}>Заявка принята</h3>
      <p className={styles.footerHint}>
        Менеджер свяжется с вами в рабочее время и подтвердит наличие, цены и сроки.
      </p>
      <p className={styles.successNumber}>№ {result.number}</p>
      {result.total_estimate ? (
        <p className={styles.footerHint}>
          Предварительная сумма: {formatAmount(result.total_estimate)} {result.currency}
        </p>
      ) : (
        <p className={styles.footerHint}>
          В заявке есть позиции без цены — сумму рассчитает менеджер.
        </p>
      )}
      <Button variant="outline" onClick={onClose}>
        Закрыть
      </Button>
    </div>
  );
}

export function RequestDrawer() {
  const { isOpen, close } = useRequestDrawer();
  const { lines, count } = useRequest();
  const [submitted, setSubmitted] = useState<RequestCreated | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const restoreFocusTo = useRef<HTMLElement | null>(null);

  const handleClose = useCallback(() => {
    close();
    setSubmitted(null);
  }, [close]);

  useEffect(() => {
    if (!isOpen) return;

    restoreFocusTo.current = document.activeElement as HTMLElement | null;
    const { overflow } = document.body.style;
    document.body.style.overflow = 'hidden';

    const panel = panelRef.current;
    panel?.querySelector<HTMLElement>(FOCUSABLE)?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault();
        handleClose();
        return;
      }
      if (event.key !== 'Tab' || !panel) return;

      const focusable = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!first || !last) return;

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = overflow;
      restoreFocusTo.current?.focus();
    };
  }, [isOpen, handleClose]);

  if (!isOpen) return null;

  const totalPositions = `${count} ${count === 1 ? 'позиция' : count >= 2 && count <= 4 ? 'позиции' : 'позиций'}`;

  return (
    <div
      className={styles.overlay}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) handleClose();
      }}
    >
      <div
        className={styles.panel}
        role="dialog"
        aria-modal="true"
        aria-label="Заявка"
        ref={panelRef}
      >
        <header className={styles.header}>
          <div>
            <div className={styles.title}>Заявка</div>
            <div className={styles.counter}>{submitted ? 'Отправлена' : totalPositions}</div>
          </div>
          <button
            type="button"
            className={styles.close}
            onClick={handleClose}
            aria-label="Закрыть заявку"
          >
            ✕
          </button>
        </header>

        <div className={styles.body}>
          {submitted ? (
            <SubmittedView result={submitted} onClose={handleClose} />
          ) : lines.length === 0 ? (
            <EmptyState
              title="В заявке пока пусто"
              text="Добавьте позиции из каталога — мы рассчитаем стоимость с учётом объёма."
              action={
                <ButtonLink href="/catalog" onClick={handleClose}>
                  Перейти в каталог
                </ButtonLink>
              }
            />
          ) : (
            <>
              <RequestLines />
              <RequestForm onSuccess={setSubmitted} />
            </>
          )}
        </div>

        {!submitted && lines.length > 0 ? (
          <footer className={styles.footer}>
            <p className={styles.footerHint}>
              Итог считает менеджер: цена зависит от объёма, а часть позиций — по запросу.
            </p>
            <p className={styles.counter}>
              {lines
                .map((line) => `${formatQuantity(String(line.quantity))} ${unitLabel(line.unit)}`)
                .join(' · ')}
            </p>
          </footer>
        ) : null}
      </div>
    </div>
  );
}
