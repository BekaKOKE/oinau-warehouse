/**
 * Вход в кабинет.
 *
 * «Запомнить» отдельной галочкой не нужно: сессию помнит refresh-cookie
 * (30 дней), access-токен живёт в памяти. Неподтверждённый email —
 * отдельное состояние с кнопкой повторной отправки письма, а не общая
 * ошибка «неверный пароль».
 */

'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';

import { ApiError } from '@/lib/api/client';
import { resendVerification } from '@/lib/api/customer-auth';
import { describeCabinetError, validateEmail } from '@/lib/cabinet/format';
import { safeNextPath } from '@/lib/cabinet/navigation';
import { Button } from '@/components/ui/Button';
import { TextField } from '@/components/ui/Field';
import { useCustomerSession } from './CustomerSessionProvider';
import { FormAlert, PasswordField } from './CabinetUi';
import { useToast } from './Toaster';
import styles from './Cabinet.module.css';

type Errors = Partial<Record<'email' | 'password', string>>;

export function LoginForm({ next }: { next?: string }) {
  const router = useRouter();
  const toast = useToast();
  const { login, status } = useCustomerSession();
  const target = safeNextPath(next);

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [errors, setErrors] = useState<Errors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [unverified, setUnverified] = useState(false);
  const [pending, setPending] = useState(false);
  const [resending, setResending] = useState(false);

  // Уже вошедшему форма не нужна.
  useEffect(() => {
    if (status === 'authenticated' && !pending) router.replace(target);
  }, [status, pending, router, target]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    setUnverified(false);

    const found: Errors = {
      email: validateEmail(email),
      password: password ? undefined : 'Введите пароль',
    };
    setErrors(found);
    if (found.email || found.password) return;

    setPending(true);
    try {
      await login(email.trim(), password);
      router.replace(target);
    } catch (error) {
      if (error instanceof ApiError && error.code === 'email_not_verified') {
        setUnverified(true);
      } else {
        setFormError(describeCabinetError(error));
      }
      setPending(false);
    }
  }

  async function handleResend() {
    setResending(true);
    try {
      const result = await resendVerification(email.trim());
      toast.success(result.detail);
    } catch (error) {
      toast.error(describeCabinetError(error));
    } finally {
      setResending(false);
    }
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit} noValidate>
      {formError ? <FormAlert>{formError}</FormAlert> : null}
      {unverified ? (
        <FormAlert tone="info">
          <p>Email ещё не подтверждён. Откройте ссылку из письма, отправленного при регистрации.</p>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={handleResend}
            disabled={resending}
            className={styles.alertAction}
          >
            {resending ? 'Отправляем…' : 'Отправить письмо ещё раз'}
          </Button>
        </FormAlert>
      ) : null}

      <TextField
        label="Email"
        type="email"
        name="email"
        autoComplete="email"
        inputMode="email"
        required
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        error={errors.email}
      />

      <PasswordField
        label="Пароль"
        name="password"
        autoComplete="current-password"
        value={password}
        onChange={setPassword}
        error={errors.password}
      />

      <div className={styles.formRowEnd}>
        <Link href="/cabinet/reset-password" className={styles.textLink}>
          Забыли пароль?
        </Link>
      </div>

      <Button type="submit" size="lg" block disabled={pending} aria-busy={pending}>
        {pending ? 'Входим…' : 'Войти'}
      </Button>
    </form>
  );
}
