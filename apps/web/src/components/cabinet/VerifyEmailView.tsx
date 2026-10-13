/**
 * Подтверждение email по ссылке из письма.
 *
 * Токен отправляется один раз при открытии страницы. Ref защищает
 * от двойного запуска эффекта в StrictMode: токен одноразовый, и второй
 * запрос показал бы «ссылка недействительна» уже подтвердившему человеку.
 */

'use client';

import { useEffect, useRef, useState } from 'react';

import { resendVerification, verifyEmail } from '@/lib/api/customer-auth';
import { describeCabinetError, validateEmail } from '@/lib/cabinet/format';
import { Button, ButtonLink } from '@/components/ui/Button';
import { TextField } from '@/components/ui/Field';
import { FormAlert } from './CabinetUi';
import styles from './Cabinet.module.css';

type State = 'verifying' | 'success' | 'failed' | 'missing';

export function VerifyEmailView({ token }: { token?: string }) {
  const [state, setState] = useState<State>(token ? 'verifying' : 'missing');
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (!token || started.current) return;
    started.current = true;
    verifyEmail(token)
      .then(() => setState('success'))
      .catch((caught: unknown) => {
        setError(describeCabinetError(caught));
        setState('failed');
      });
  }, [token]);

  if (state === 'verifying') {
    return (
      <div className={styles.resultPanel} role="status" aria-busy="true">
        <span className={`${styles.resultIcon} ${styles.resultSpinner}`} aria-hidden="true" />
        <h2 className={styles.resultTitle}>Подтверждаем email…</h2>
        <p className={styles.resultText}>Это займёт пару секунд.</p>
      </div>
    );
  }

  if (state === 'success') {
    return (
      <div className={styles.resultPanel} role="status">
        <span className={`${styles.resultIcon} ${styles.resultIconSuccess}`} aria-hidden="true">
          ✓
        </span>
        <h2 className={styles.resultTitle}>Email подтверждён</h2>
        <p className={styles.resultText}>Аккаунт активен — войдите, чтобы открыть кабинет.</p>
        <div className={styles.resultActions}>
          <ButtonLink href="/cabinet/login" size="lg">
            Войти в кабинет
          </ButtonLink>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.resultStack}>
      <div className={styles.resultPanel} role={state === 'failed' ? 'alert' : undefined}>
        <span className={`${styles.resultIcon} ${styles.resultIconError}`} aria-hidden="true">
          !
        </span>
        <h2 className={styles.resultTitle}>
          {state === 'missing' ? 'Ссылка неполная' : 'Не удалось подтвердить email'}
        </h2>
        <p className={styles.resultText}>
          {state === 'missing'
            ? 'Откройте ссылку из письма целиком или запросите новое письмо.'
            : error}
        </p>
      </div>
      <ResendVerificationForm />
    </div>
  );
}

export function ResendVerificationForm() {
  const [email, setEmail] = useState('');
  const [fieldError, setFieldError] = useState<string>();
  const [message, setMessage] = useState<{ tone: 'success' | 'error'; text: string } | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);
    const found = validateEmail(email);
    setFieldError(found);
    if (found) return;
    setPending(true);
    try {
      const result = await resendVerification(email.trim());
      setMessage({ tone: 'success', text: result.detail });
    } catch (error) {
      setMessage({ tone: 'error', text: describeCabinetError(error) });
    } finally {
      setPending(false);
    }
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit} noValidate>
      <h3 className={styles.formSubtitle}>Отправить письмо повторно</h3>
      {message ? <FormAlert tone={message.tone}>{message.text}</FormAlert> : null}
      <TextField
        label="Email"
        type="email"
        name="email"
        autoComplete="email"
        inputMode="email"
        required
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        error={fieldError}
      />
      <Button type="submit" variant="secondary" size="lg" block disabled={pending}>
        {pending ? 'Отправляем…' : 'Отправить письмо'}
      </Button>
    </form>
  );
}
