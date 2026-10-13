/**
 * Редактирование профиля.
 *
 * Email показывается, но не редактируется: на него приходят ссылки
 * восстановления доступа, и его смена — отдельный сценарий
 * с подтверждением нового адреса. Backend такой PATCH отклоняет.
 *
 * Отправляются только изменённые поля.
 */

'use client';

import { useEffect, useMemo, useState } from 'react';

import type { CustomerProfileUpdate } from '@oinau/api-types';

import { updateProfile } from '@/lib/api/customer';
import {
  describeCabinetError,
  fieldErrorsFrom,
  formatDate,
  validatePhone,
} from '@/lib/cabinet/format';
import { Button } from '@/components/ui/Button';
import { TextField } from '@/components/ui/Field';
import { FormAlert, PageHead } from './CabinetUi';
import { useCustomerSession } from './CustomerSessionProvider';
import { useToast } from './Toaster';
import styles from './Cabinet.module.css';

type Values = { contact_name: string; company_name: string; phone: string };
type Errors = Partial<Record<keyof Values, string>>;

export function ProfileForm() {
  const { profile, setProfile } = useCustomerSession();
  const toast = useToast();
  const [errors, setErrors] = useState<Errors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const initial = useMemo<Values>(
    () => ({
      contact_name: profile?.contact_name ?? '',
      company_name: profile?.company_name ?? '',
      phone: profile?.phone ?? '',
    }),
    [profile],
  );
  const [values, setValues] = useState<Values>(initial);

  useEffect(() => setValues(initial), [initial]);

  if (!profile) return null;

  const changes: CustomerProfileUpdate = {};
  if (values.contact_name.trim() !== initial.contact_name) {
    changes.contact_name = values.contact_name.trim();
  }
  if (values.company_name.trim() !== initial.company_name) {
    changes.company_name = values.company_name.trim() || null;
  }
  if (values.phone.trim() !== initial.phone) changes.phone = values.phone.trim();
  const dirty = Object.keys(changes).length > 0;

  const set = (key: keyof Values) => (value: string) =>
    setValues((current) => ({ ...current, [key]: value }));

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    const found: Errors = {
      contact_name: values.contact_name.trim() ? undefined : 'Укажите контактное лицо',
      phone: validatePhone(values.phone),
    };
    setErrors(found);
    if (found.contact_name || found.phone || !dirty) return;

    setPending(true);
    try {
      const updated = await updateProfile(changes);
      setProfile(updated);
      toast.success('Профиль сохранён');
    } catch (error) {
      const fields = fieldErrorsFrom(error);
      if (Object.keys(fields).length > 0) setErrors(fields);
      setFormError(describeCabinetError(error));
    } finally {
      setPending(false);
    }
  }

  return (
    <>
      <PageHead title="Профиль" lead="Контактные данные подставляются в заявки из кабинета." />

      <div className={styles.profileGrid}>
        <form className={`${styles.panel} ${styles.form}`} onSubmit={handleSubmit} noValidate>
          <h2 className={styles.panelTitle}>Контактные данные</h2>
          {formError ? <FormAlert>{formError}</FormAlert> : null}

          <div className={styles.formGrid}>
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
            />
            <TextField
              label="Телефон"
              type="tel"
              name="phone"
              autoComplete="tel"
              inputMode="tel"
              required
              value={values.phone}
              onChange={(event) => set('phone')(event.target.value)}
              error={errors.phone}
            />
          </div>

          <div className={styles.formActions}>
            <Button type="submit" disabled={!dirty || pending} aria-busy={pending}>
              {pending ? 'Сохраняем…' : 'Сохранить изменения'}
            </Button>
            {dirty && !pending ? (
              <Button type="button" variant="outline" onClick={() => setValues(initial)}>
                Отменить
              </Button>
            ) : null}
          </div>
        </form>

        <section className={styles.panel} aria-labelledby="account-info">
          <h2 id="account-info" className={styles.panelTitle}>
            Аккаунт
          </h2>
          <dl className={styles.details}>
            <div>
              <dt>Email</dt>
              <dd className={styles.breakAll}>{profile.email}</dd>
            </div>
            <div>
              <dt>Email подтверждён</dt>
              <dd>{profile.email_verified_at ? formatDate(profile.email_verified_at) : 'Нет'}</dd>
            </div>
            <div>
              <dt>В кабинете с</dt>
              <dd>{formatDate(profile.created_at)}</dd>
            </div>
            <div>
              <dt>Последний вход</dt>
              <dd>{formatDate(profile.last_login_at)}</dd>
            </div>
          </dl>
          <p className={styles.panelNote}>
            Email используется для входа и восстановления доступа, поэтому здесь его изменить
            нельзя. Чтобы сменить адрес, свяжитесь с менеджером.
          </p>
        </section>
      </div>
    </>
  );
}
