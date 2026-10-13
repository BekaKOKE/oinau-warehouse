/**
 * Восстановление пароля: запрос ссылки и установка нового пароля.
 *
 * Шаг запроса всегда заканчивается одним и тем же сообщением —
 * страница не подсказывает, есть ли аккаунт с таким адресом.
 */

'use client';

import { useState } from 'react';

import { confirmPasswordReset, requestPasswordReset } from '@/lib/api/customer-auth';
import {
  describeCabinetError,
  fieldErrorsFrom,
  validateEmail,
  validatePassword,
} from '@/lib/cabinet/format';
import { Button, ButtonLink } from '@/components/ui/Button';
import { TextField } from '@/components/ui/Field';
import { FormAlert, PasswordField } from './CabinetUi';
import styles from './Cabinet.module.css';

const GENERIC_SENT =
  'Если аккаунт с таким адресом существует, на него отправлена ссылка для сброса пароля. ' +
  'Ссылка действует 60 минут.';

export function ResetPasswordView({ token }: { token?: string }) {
  return token ? <NewPasswordForm token={token} /> : <RequestResetForm />;
}

function RequestResetForm() {
  const [email, setEmail] = useState('');
  const [fieldError, setFieldError] = useState<string>();
  const [formError, setFormError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    const found = validateEmail(email);
    setFieldError(found);
    if (found) return;
    setPending(true);
    try {
      await requestPasswordReset(email.trim());
      setSent(true);
    } catch (error) {
      setFormError(describeCabinetError(error));
    } finally {
      setPending(false);
    }
  }

  if (sent) {
    return (
      <div className={styles.resultPanel} role="status">
        <span className={styles.resultIcon} aria-hidden="true">
          ✉
        </span>
        <h2 className={styles.resultTitle}>Проверьте почту</h2>
        <p className={styles.resultText}>{GENERIC_SENT}</p>
        <div className={styles.resultActions}>
          <ButtonLink href="/cabinet/login" size="lg" variant="outline">
            Вернуться ко входу
          </ButtonLink>
        </div>
      </div>
    );
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit} noValidate>
      {formError ? <FormAlert>{formError}</FormAlert> : null}
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
      <Button type="submit" size="lg" block disabled={pending} aria-busy={pending}>
        {pending ? 'Отправляем…' : 'Получить ссылку'}
      </Button>
    </form>
  );
}

function NewPasswordForm({ token }: { token: string }) {
  const [password, setPassword] = useState('');
  const [repeat, setRepeat] = useState('');
  const [errors, setErrors] = useState<{ password?: string; repeat?: string }>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    const found = {
      password: validatePassword(password),
      repeat: password === repeat ? undefined : 'Пароли не совпадают',
    };
    setErrors(found);
    if (found.password || found.repeat) return;
    setPending(true);
    try {
      await confirmPasswordReset(token, password);
      setDone(true);
    } catch (error) {
      const fields = fieldErrorsFrom(error);
      if (fields.new_password) setErrors({ password: fields.new_password });
      setFormError(describeCabinetError(error));
    } finally {
      setPending(false);
    }
  }

  if (done) {
    return (
      <div className={styles.resultPanel} role="status">
        <span className={`${styles.resultIcon} ${styles.resultIconSuccess}`} aria-hidden="true">
          ✓
        </span>
        <h2 className={styles.resultTitle}>Пароль изменён</h2>
        <p className={styles.resultText}>Все прежние сессии завершены. Войдите с новым паролем.</p>
        <div className={styles.resultActions}>
          <ButtonLink href="/cabinet/login" size="lg">
            Войти
          </ButtonLink>
        </div>
      </div>
    );
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit} noValidate>
      {formError ? (
        <FormAlert>
          {formError}{' '}
          <ButtonLink href="/cabinet/reset-password" variant="ghost" size="sm">
            Запросить новую ссылку
          </ButtonLink>
        </FormAlert>
      ) : null}
      <PasswordField
        label="Новый пароль"
        name="new_password"
        autoComplete="new-password"
        value={password}
        onChange={setPassword}
        error={errors.password}
        hint="Не короче 12 символов"
      />
      <PasswordField
        label="Повторите пароль"
        name="repeat_password"
        autoComplete="new-password"
        value={repeat}
        onChange={setRepeat}
        error={errors.repeat}
      />
      <Button type="submit" size="lg" block disabled={pending} aria-busy={pending}>
        {pending ? 'Сохраняем…' : 'Сохранить пароль'}
      </Button>
    </form>
  );
}
