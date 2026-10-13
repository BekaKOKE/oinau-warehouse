/**
 * Контактная форма заявки.
 *
 * Проверка повторяет правила backend ровно настолько, чтобы посетитель
 * не отправлял заведомо неверную форму. Последнее слово — за сервером:
 * его сообщения показываются как есть, в том числе по конкретным
 * позициям (недоступный товар, количество ниже минимальной партии).
 *
 * Вошедший клиент отправляет заявку через кабинет: контакты подставляются
 * из профиля, а заявка появляется в истории. Гость — через публичный API,
 * как и раньше.
 */

'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

import type { RequestCreated } from '@oinau/api-types';

import { useCustomerSession } from '@/components/cabinet/CustomerSessionProvider';
import { ApiError, describeError } from '@/lib/api/client';
import { submitCustomerRequest } from '@/lib/api/customer';
import { newIdempotencyKey, submitRequest } from '@/lib/api/requests';
import { describeItemError } from '@/lib/request-errors';
import { Button } from '@/components/ui/Button';
import { TextAreaField, TextField } from '@/components/ui/Field';
import { useRequest } from './RequestProvider';
import styles from './RequestDrawer.module.css';

type FieldErrors = Partial<Record<'name' | 'phone' | 'email', string>>;

const PHONE_DIGITS = /\d/g;

function validate(values: { name: string; phone: string; email: string }): FieldErrors {
  const errors: FieldErrors = {};
  if (!values.name.trim()) errors.name = 'Укажите, как к вам обращаться';
  const digits = values.phone.match(PHONE_DIGITS)?.length ?? 0;
  if (!values.phone.trim()) errors.phone = 'Укажите телефон для связи';
  else if (digits < 5 || digits > 15) errors.phone = 'В номере должно быть от 5 до 15 цифр';
  if (values.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(values.email)) {
    errors.email = 'Проверьте адрес электронной почты';
  }
  return errors;
}

export function RequestForm({ onSuccess }: { onSuccess: (result: RequestCreated) => void }) {
  const { lines, clear } = useRequest();
  const { status: sessionStatus, profile } = useCustomerSession();
  const signedIn = sessionStatus === 'authenticated' && profile !== null;

  const [values, setValues] = useState({
    name: '',
    phone: '',
    email: '',
    company: '',
    comment: '',
  });
  const [errors, setErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  // Ключ идемпотентности живёт столько же, сколько открытая форма:
  // повтор после обрыва сети вернёт ту же заявку, а не создаст вторую.
  const idempotencyKey = useRef(newIdempotencyKey());

  // Профиль приходит после восстановления сессии — заполняем только
  // пустые поля, чтобы не затереть то, что человек уже ввёл.
  useEffect(() => {
    if (!profile) return;
    setValues((current) => ({
      ...current,
      name: current.name || profile.contact_name,
      phone: current.phone || profile.phone,
      email: current.email || profile.email,
      company: current.company || (profile.company_name ?? ''),
    }));
  }, [profile]);

  const disabled = useMemo(() => lines.length === 0 || pending, [lines.length, pending]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);

    const found = validate(values);
    setErrors(found);
    if (Object.keys(found).length > 0) return;

    setPending(true);
    try {
      const payload = {
        name: values.name.trim(),
        phone: values.phone.trim(),
        email: values.email.trim() || null,
        company: values.company.trim() || null,
        comment: values.comment.trim() || null,
        items: lines.map((line) => ({
          sku: line.sku,
          quantity: String(line.quantity),
          ...(line.color ? { color: line.color } : {}),
        })),
      };
      const result = signedIn
        ? await submitCustomerRequest(payload, idempotencyKey.current)
        : await submitRequest(payload, idempotencyKey.current);
      clear();
      onSuccess(result);
    } catch (error) {
      setFormError(error instanceof ApiError ? describeItemError(error) : describeError(error));
      // Новая попытка после ошибки — новая заявка, а не повтор прежней.
      idempotencyKey.current = newIdempotencyKey();
    } finally {
      setPending(false);
    }
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit} noValidate>
      <h3 className={styles.formTitle}>Контакты для ответа</h3>
      {signedIn ? (
        <p className={styles.formNote}>
          Контакты взяты из профиля кабинета. Заявка появится в разделе «Заявки».
        </p>
      ) : null}

      <div className={styles.formRow}>
        <TextField
          label="Имя"
          required
          name="name"
          autoComplete="name"
          value={values.name}
          error={errors.name}
          onChange={(event) => setValues({ ...values, name: event.target.value })}
        />
        <TextField
          label="Телефон"
          required
          name="phone"
          type="tel"
          autoComplete="tel"
          placeholder="+7 707 000 00 00"
          value={values.phone}
          error={errors.phone}
          onChange={(event) => setValues({ ...values, phone: event.target.value })}
        />
      </div>

      <div className={styles.formRow}>
        <TextField
          label="Email"
          name="email"
          type="email"
          autoComplete="email"
          hint="Пришлём счёт и спецификацию"
          value={values.email}
          error={errors.email}
          onChange={(event) => setValues({ ...values, email: event.target.value })}
        />
        <TextField
          label="Компания"
          name="company"
          autoComplete="organization"
          value={values.company}
          onChange={(event) => setValues({ ...values, company: event.target.value })}
        />
      </div>

      <TextAreaField
        label="Комментарий"
        name="comment"
        placeholder="Сроки, цвет, нестандартные размеры, ссылка на спецификацию"
        value={values.comment}
        onChange={(event) => setValues({ ...values, comment: event.target.value })}
      />

      {formError ? (
        <p className={styles.formError} role="alert">
          {formError}
        </p>
      ) : null}

      <Button type="submit" size="lg" block disabled={disabled}>
        {pending ? 'Отправляем…' : 'Отправить заявку'}
      </Button>
      <p className={styles.formNote}>
        Нажимая кнопку, вы соглашаетесь на обработку контактных данных для ответа на заявку. Оплата
        на сайте не производится — менеджер свяжется с вами и выставит счёт.
      </p>
    </form>
  );
}
