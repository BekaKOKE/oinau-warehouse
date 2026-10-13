/**
 * Регистрация клиента.
 *
 * Backend отвечает одинаково для нового и уже занятого адреса, поэтому
 * и экран после отправки один: «Проверьте почту». Сказать «такой email
 * уже есть» — значит подтвердить чужую регистрацию любому желающему.
 */

'use client';

import { useState } from 'react';

import { registerCustomer, resendVerification } from '@/lib/api/customer-auth';
import {
  describeCabinetError,
  fieldErrorsFrom,
  validateEmail,
  validatePassword,
  validatePhone,
} from '@/lib/cabinet/format';
import { Button, ButtonLink } from '@/components/ui/Button';
import { TextField } from '@/components/ui/Field';
import { FormAlert, PasswordField } from './CabinetUi';
import { useToast } from './Toaster';
import styles from './Cabinet.module.css';

type Values = {
  email: string;
  password: string;
  contact_name: string;
  company_name: string;
  phone: string;
};

type Errors = Partial<Record<keyof Values, string>>;

function validate(values: Values): Errors {
  return {
    email: validateEmail(values.email),
    password: validatePassword(values.password),
    contact_name: values.contact_name.trim() ? undefined : 'Укажите контактное лицо',
    phone: validatePhone(values.phone),
  };
}

export function RegisterForm() {
  const toast = useToast();
  const [values, setValues] = useState<Values>({
    email: '',
    password: '',
    contact_name: '',
    company_name: '',
    phone: '',
  });
  const [errors, setErrors] = useState<Errors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [resending, setResending] = useState(false);

  const set = (key: keyof Values) => (value: string) =>
    setValues((current) => ({ ...current, [key]: value }));

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    const found = validate(values);
    setErrors(found);
    if (Object.values(found).some(Boolean)) return;

    setPending(true);
    try {
      await registerCustomer({
        email: values.email.trim(),
        password: values.password,
        contact_name: values.contact_name.trim(),
        company_name: values.company_name.trim() || null,
        phone: values.phone.trim(),
      });
      setSentTo(values.email.trim());
    } catch (error) {
      const fields = fieldErrorsFrom(error);
      if (Object.keys(fields).length > 0) setErrors(fields);
      setFormError(describeCabinetError(error));
    } finally {
      setPending(false);
    }
  }

  async function handleResend() {
    if (!sentTo) return;
    setResending(true);
    try {
      const result = await resendVerification(sentTo);
      toast.success(result.detail);
    } catch (error) {
      toast.error(describeCabinetError(error));
    } finally {
      setResending(false);
    }
  }

  if (sentTo) {
    return (
      <div className={styles.resultPanel} role="status">
        <span className={styles.resultIcon} aria-hidden="true">
          ✉
        </span>
        <h2 className={styles.resultTitle}>Проверьте email</h2>
        <p className={styles.resultText}>
          Если адрес <strong>{sentTo}</strong> ещё не зарегистрирован, мы отправили на него письмо
          со ссылкой для подтверждения. Ссылка действует 24 часа.
        </p>
        <div className={styles.resultActions}>
          <ButtonLink href="/cabinet/login" size="lg">
            Перейти ко входу
          </ButtonLink>
          <Button
            type="button"
            variant="outline"
            size="lg"
            onClick={handleResend}
            disabled={resending}
          >
            {resending ? 'Отправляем…' : 'Отправить письмо ещё раз'}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit} noValidate>
      {formError ? <FormAlert>{formError}</FormAlert> : null}

      <div className={styles.formGrid}>
        <TextField
          label="Email"
          type="email"
          name="email"
          autoComplete="email"
          inputMode="email"
          required
          value={values.email}
          onChange={(event) => set('email')(event.target.value)}
          error={errors.email}
        />
        <PasswordField
          label="Пароль"
          name="password"
          autoComplete="new-password"
          value={values.password}
          onChange={set('password')}
          error={errors.password}
          hint="Не короче 12 символов"
        />
        <TextField
          label="Контактное лицо"
          name="contact_name"
          autoComplete="name"
          required
          value={values.contact_name}
          onChange={(event) => set('contact_name')(event.target.value)}
          error={errors.contact_name}
        />
        <TextField
          label="Компания"
          name="company_name"
          autoComplete="organization"
          value={values.company_name}
          onChange={(event) => set('company_name')(event.target.value)}
          error={errors.company_name}
          hint="Необязательно"
        />
        <TextField
          label="Телефон"
          type="tel"
          name="phone"
          autoComplete="tel"
          inputMode="tel"
          required
          placeholder="+7 700 000 00 00"
          value={values.phone}
          onChange={(event) => set('phone')(event.target.value)}
          error={errors.phone}
        />
      </div>

      <Button type="submit" size="lg" block disabled={pending} aria-busy={pending}>
        {pending ? 'Регистрируем…' : 'Зарегистрироваться'}
      </Button>
      <p className={styles.formNote}>
        Нажимая «Зарегистрироваться», вы соглашаетесь на обработку контактных данных для работы с
        заявками.
      </p>
    </form>
  );
}
