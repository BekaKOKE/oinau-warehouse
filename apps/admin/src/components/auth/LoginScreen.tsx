'use client';

/**
 * Вход сотрудника.
 *
 * Текст ошибки неверного пароля берётся у backend как есть: он
 * намеренно не различает «нет такого email» и «неверный пароль».
 * Блокировку после серии неудачных попыток и ограничение частоты
 * backend тоже объясняет сам.
 */

import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useState, type FormEvent } from 'react';

import { useSession } from '@/components/session/SessionProvider';
import { BrandLogo } from '@/components/ui/BrandLogo';
import { Button } from '@/components/ui/Button';
import { Field, Input } from '@/components/ui/Field';
import { Icon } from '@/components/ui/Icon';
import { ApiError } from '@/lib/api/client';
import { describeError, extractFieldErrors } from '@/lib/errors';
import { safeNextPath } from '@/lib/navigation';

import styles from './LoginScreen.module.css';

function loginErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 401) {
    return error.message || 'Неверный email или пароль';
  }
  return describeError(error);
}

export function LoginScreen() {
  const { status, login } = useSession();
  const router = useRouter();
  const searchParams = useSearchParams();
  const next = safeNextPath(searchParams.get('next'));

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (status === 'authenticated') router.replace(next);
  }, [status, next, router]);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setFormError(null);
    setFieldErrors({});
    try {
      await login(email.trim(), password);
      // Переход сделает эффект выше, когда статус станет authenticated.
    } catch (error) {
      const fields = extractFieldErrors(error);
      if (Object.keys(fields).length > 0) setFieldErrors(fields);
      else setFormError(loginErrorMessage(error));
      setPassword('');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className={styles.screen}>
      <div className={styles.aside} aria-hidden="true">
        <div className={styles.asideInner}>
          <BrandLogo tone="white" height={40} />
          <p className={styles.asideTitle}>Панель управления</p>
          <p className={styles.asideText}>
            Каталог комплектующих, заявки клиентов и содержимое сайта — в одной панели.
          </p>
        </div>
      </div>

      <main className={styles.main}>
        <div className={styles.card}>
          <div className={styles.header}>
            <span className={styles.mobileLogo} aria-hidden="true">
              <BrandLogo height={28} />
            </span>
            <h1 className={styles.title}>Вход в панель управления</h1>
            <p className={styles.subtitle}>Только для сотрудников OINAU PRO</p>
          </div>

          {formError ? (
            <div className={styles.alert} role="alert">
              <Icon name="alert" size={16} />
              <span>{formError}</span>
            </div>
          ) : null}

          <form className={styles.form} onSubmit={onSubmit} noValidate>
            <Field label="Email" error={fieldErrors.email}>
              <Input
                type="email"
                name="email"
                autoComplete="username"
                inputMode="email"
                required
                autoFocus
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </Field>
            <Field label="Пароль" error={fieldErrors.password}>
              <Input
                type="password"
                name="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </Field>
            <Button
              type="submit"
              variant="primary"
              loading={submitting}
              disabled={!email || !password}
              className={styles.submit}
            >
              Войти
            </Button>
          </form>

          <p className={styles.footnote}>
            <Icon name="lock" size={14} />
            Нет доступа или забыли пароль — обратитесь к администратору.
          </p>
        </div>
      </main>
    </div>
  );
}
