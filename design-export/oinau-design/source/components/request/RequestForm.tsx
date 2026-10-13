/**
 * Контактная форма заявки.
 *
 * Проверка повторяет правила backend ровно настолько, чтобы посетитель
 * не отправлял заведомо неверную форму. Последнее слово — за сервером:
 * его сообщения показываются как есть, в том числе по конкретным
 * позициям (недоступный товар, количество ниже минимальной партии).
 */

'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

import type { Region, RequestCreated } from '@oinau/api-types';

import { ApiError, describeError } from '@/lib/api/client';
import { fetchRegions, newIdempotencyKey, submitRequest } from '@/lib/api/requests';
import { Button } from '@/components/ui/Button';
import { SelectField, TextAreaField, TextField } from '@/components/ui/Field';
import { useRequest } from './RequestProvider';
import styles from './RequestDrawer.module.css';

type FieldErrors = Partial<Record<'name' | 'phone' | 'email' | 'region', string>>;

const PHONE_DIGITS = /\d/g;

function validate(values: {
  name: string;
  phone: string;
  email: string;
  region: string;
}): FieldErrors {
  const errors: FieldErrors = {};
  if (!values.name.trim()) errors.name = 'Укажите, как к вам обращаться';
  const digits = values.phone.match(PHONE_DIGITS)?.length ?? 0;
  if (!values.phone.trim()) errors.phone = 'Укажите телефон для связи';
  else if (digits < 5 || digits > 15) errors.phone = 'В номере должно быть от 5 до 15 цифр';
  if (values.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(values.email)) {
    errors.email = 'Проверьте адрес электронной почты';
  }
  if (!values.region) errors.region = 'Выберите регион доставки';
  return errors;
}

/**
 * Ошибки, привязанные к конкретным позициям, backend возвращает
 * в `details`. Показать их общим текстом мало: нужно назвать артикулы.
 */
function describeItemError(error: ApiError): string {
  const details = error.details ?? {};
  if (error.code === 'product_unavailable' && Array.isArray(details.skus)) {
    return `${error.message}: ${details.skus.join(', ')}. Уберите эти позиции из заявки.`;
  }
  if (error.code === 'quantity_below_minimum' && Array.isArray(details.items)) {
    const parts = details.items
      .filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null)
      .map((item) => `${String(item.sku)} — минимум ${String(item.min_order_qty)}`);
    return `${error.message}: ${parts.join('; ')}`;
  }
  if (error.code === 'rate_limited') {
    return 'Слишком много заявок с этого адреса. Попробуйте позже или напишите в WhatsApp.';
  }
  return describeError(error);
}

export function RequestForm({ onSuccess }: { onSuccess: (result: RequestCreated) => void }) {
  const { lines, clear } = useRequest();

  const [regions, setRegions] = useState<Region[]>([]);
  const [regionsFailed, setRegionsFailed] = useState(false);
  const [values, setValues] = useState({
    name: '',
    phone: '',
    email: '',
    company: '',
    region: '',
    comment: '',
  });
  const [errors, setErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  // Ключ идемпотентности живёт столько же, сколько открытая форма:
  // повтор после обрыва сети вернёт ту же заявку, а не создаст вторую.
  const idempotencyKey = useRef(newIdempotencyKey());

  useEffect(() => {
    let cancelled = false;
    fetchRegions()
      .then((items) => {
        if (cancelled) return;
        setRegions(items);
        setValues((current) =>
          current.region || items.length === 0
            ? current
            : { ...current, region: String(items[0]?.id ?? '') },
        );
      })
      .catch(() => {
        if (!cancelled) setRegionsFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const disabled = useMemo(() => lines.length === 0 || pending, [lines.length, pending]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);

    const found = validate(values);
    setErrors(found);
    if (Object.keys(found).length > 0) return;

    setPending(true);
    try {
      const result = await submitRequest(
        {
          name: values.name.trim(),
          phone: values.phone.trim(),
          email: values.email.trim() || null,
          company: values.company.trim() || null,
          region_id: Number(values.region),
          comment: values.comment.trim() || null,
          items: lines.map((line) => ({ sku: line.sku, quantity: String(line.quantity) })),
        },
        idempotencyKey.current,
      );
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

      <SelectField
        label="Регион доставки"
        required
        name="region"
        value={values.region}
        error={
          errors.region ?? (regionsFailed ? 'Не удалось загрузить список регионов' : undefined)
        }
        onChange={(event) => setValues({ ...values, region: event.target.value })}
      >
        <option value="">Выберите регион</option>
        {regions.map((region) => (
          <option key={region.id} value={region.id}>
            {region.name}
          </option>
        ))}
      </SelectField>

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
