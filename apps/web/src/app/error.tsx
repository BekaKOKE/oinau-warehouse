/**
 * Экран непредвиденной ошибки.
 *
 * Показывается вместо белого экрана, когда серверный компонент упал
 * (например, API недоступен). Текст ошибки наружу не выводится —
 * посетителю он ничего не говорит, а в нём могут быть внутренние
 * адреса.
 */

'use client';

import { useEffect } from 'react';

import { Button, ButtonLink } from '@/components/ui/Button';
import { ErrorState } from '@/components/ui/States';
import styles from '@/components/content/Page.module.css';

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('page_error', error.digest ?? error.message);
  }, [error]);

  return (
    <div className={`container ${styles.page}`}>
      <header className={styles.header}>
        <h1 className={styles.title}>Что-то пошло не так</h1>
      </header>
      <section className={styles.section}>
        <ErrorState
          title="Не удалось загрузить страницу"
          text="Похоже, сервис временно недоступен. Попробуйте обновить страницу через минуту."
          action={
            <>
              <Button onClick={reset}>Повторить</Button>
              <ButtonLink href="/" variant="outline">
                На главную
              </ButtonLink>
            </>
          }
        />
      </section>
    </div>
  );
}
