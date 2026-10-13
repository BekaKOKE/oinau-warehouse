/**
 * Корзина — выезжающая панель.
 *
 * Оплаты на сайте нет: «корзина» собирает позиции, а отправляется из
 * неё заявка менеджеру, который выставит счёт. Поведение модального окна
 * (фокус внутри, Esc, блокировка прокрутки) — в `useModalDialog`.
 */

'use client';

import { useCallback, useRef, useState } from 'react';

import type { RequestCreated } from '@oinau/api-types';

import { useQuickOrder } from '@/components/quick-order/QuickOrderContext';
import { Button, ButtonLink } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/States';
import { useModalDialog } from '@/components/ui/useModalDialog';
import { currencySymbol, formatAmount, plural } from '@/lib/format';
import { RequestForm } from './RequestForm';
import { RequestLines } from './RequestLines';
import { useRequestDrawer } from './RequestDrawerContext';
import { useRequest } from './RequestProvider';
import styles from './RequestDrawer.module.css';

function SubmittedView({ result, onClose }: { result: RequestCreated; onClose: () => void }) {
  return (
    <div className={styles.success}>
      <div className={styles.successMark} aria-hidden="true">
        ✓
      </div>
      <h3 className={styles.formTitle}>Заявка отправлена</h3>
      <p className={styles.footerHint}>
        Менеджер свяжется с вами в рабочее время и подтвердит наличие, цены и сроки.
      </p>
      <p className={styles.successNumber}>№ {result.number}</p>
      {result.total_estimate ? (
        <p className={styles.footerHint}>
          Предварительная сумма: {formatAmount(result.total_estimate)}{' '}
          {currencySymbol(result.currency)}
        </p>
      ) : (
        <p className={styles.footerHint}>
          В заявке есть позиции без цены — сумму рассчитает менеджер.
        </p>
      )}
      <Button variant="dark" onClick={onClose}>
        Закрыть
      </Button>
    </div>
  );
}

export function RequestDrawer() {
  const { isOpen, close } = useRequestDrawer();
  if (!isOpen) return null;
  return <DrawerPanel onClose={close} />;
}

function DrawerPanel({ onClose }: { onClose: () => void }) {
  const { lines, count } = useRequest();
  const quickOrder = useQuickOrder();
  const [submitted, setSubmitted] = useState<RequestCreated | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const handleClose = useCallback(() => {
    onClose();
    setSubmitted(null);
  }, [onClose]);

  useModalDialog(panelRef, true, handleClose);

  const positions = `${count} ${plural(count, ['позиция', 'позиции', 'позиций'])}`;

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
        aria-label="Корзина"
        ref={panelRef}
      >
        <header className={styles.header}>
          <div>
            <div className={styles.title}>Корзина</div>
            <div className={styles.counter}>{submitted ? 'Передана менеджеру' : positions}</div>
          </div>
          <button
            type="button"
            className={styles.close}
            onClick={handleClose}
            aria-label="Закрыть корзину"
          >
            <svg width="13" height="13" viewBox="0 0 14 14" aria-hidden="true">
              <path d="M2 2l10 10M12 2 2 12" stroke="currentColor" strokeWidth="1.8" />
            </svg>
          </button>
        </header>

        <div className={styles.body}>
          {submitted ? (
            <SubmittedView result={submitted} onClose={handleClose} />
          ) : lines.length === 0 ? (
            <EmptyState
              title="В корзине пока пусто"
              text="Добавьте позиции из каталога или оформите быстрый заказ: по телефону, по списку артикулов или запросом КП."
              action={
                <div className={styles.emptyActions}>
                  <ButtonLink href="/catalog" onClick={handleClose}>
                    Перейти в каталог
                  </ButtonLink>
                  <Button
                    variant="outline"
                    onClick={() => {
                      handleClose();
                      quickOrder.open();
                    }}
                  >
                    Быстрый заказ
                  </Button>
                </div>
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
              Оплаты на сайте нет: менеджер проверит наличие, рассчитает цену с учётом объёма и
              выставит счёт.
            </p>
          </footer>
        ) : null}
      </div>
    </div>
  );
}
