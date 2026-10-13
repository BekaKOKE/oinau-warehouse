'use client';

/**
 * Карточка сотрудника: заведение и правка.
 *
 * Все ограничения повторяют backend и ничего к нему не добавляют:
 * email неизменяем, свою роль и свой доступ сотрудник не меняет,
 * роль SUPERADMIN назначает только суперадминистратор. Отключение и
 * смена пароля отзывают сессии — об этом сказано прямо в форме, потому
 * что человек за экраном должен понимать последствия до нажатия.
 */

import { useEffect, useMemo, useRef, useState } from 'react';

import { useSession } from '@/components/session/SessionProvider';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Dialog, useConfirm } from '@/components/ui/Dialog';
import { Checkbox, Field, Input, Select, Switch } from '@/components/ui/Field';
import { useToast } from '@/components/ui/Toast';
import { usersApi } from '@/lib/api/endpoints';
import type { AdminUser, RolePermissions, UserRole } from '@/lib/api/types';
import { PERMISSION_LABELS, ROLE_LABELS, type PermissionCode } from '@/lib/auth/permissions';
import { formatDateTime } from '@/lib/format';
import {
  buildUserCreate,
  buildUserUpdate,
  EMPTY_USER_FORM,
  formFromUser,
  isEmptyUpdate,
  PASSWORD_MIN_LENGTH,
  ROLE_HINTS,
  ROLE_OPTIONS,
  userErrorsFromApi,
  validateUserForm,
  type UserForm,
  type UserFormErrors,
} from '@/lib/users';

import styles from './Users.module.css';

type UserDrawerProps = {
  open: boolean;
  /** null — заведение нового сотрудника. */
  user: AdminUser | null;
  roles: readonly RolePermissions[];
  onClose: () => void;
  onSaved: (user: AdminUser, created: boolean) => void;
};

function permissionLabel(code: string): string {
  return PERMISSION_LABELS[code as PermissionCode] ?? code;
}

export function UserDrawer({ open, user, roles, onClose, onSaved }: UserDrawerProps) {
  const { user: me } = useSession();
  const toast = useToast();
  const confirm = useConfirm();

  const creating = user === null;
  const initial = useMemo<UserForm>(() => (user ? formFromUser(user) : EMPTY_USER_FORM), [user]);

  const [form, setForm] = useState<UserForm>(initial);
  const [withPassword, setWithPassword] = useState(false);
  const [errors, setErrors] = useState<UserFormErrors>({});
  const [saving, setSaving] = useState(false);
  const alertRef = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    if (!open) return;
    setForm(initial);
    setWithPassword(false);
    setErrors({});
  }, [open, initial]);

  const isSelf = Boolean(me && user && me.uuid === user.uuid);
  const amSuperadmin = me?.role === 'SUPERADMIN';
  const targetIsSuperadmin = user?.role === 'SUPERADMIN';
  // Управлять суперадминистратором может только суперадминистратор —
  // то же правило проверяет backend (403 superadmin_required).
  const locked = targetIsSuperadmin && !amSuperadmin;

  const roleOptions = ROLE_OPTIONS.filter(
    (option) => option.value !== 'SUPERADMIN' || amSuperadmin || form.role === 'SUPERADMIN',
  );
  const selectedRole = roles.find((item) => item.role === form.role);

  const update = (patch: Partial<UserForm>) => setForm((current) => ({ ...current, ...patch }));

  const save = async () => {
    const found = validateUserForm(form, { creating, withPassword });
    if (Object.keys(found).length > 0) {
      setErrors(found);
      return;
    }

    if (!creating && initial.isActive && !form.isActive) {
      const agreed = await confirm({
        title: `Отключить ${form.fullName.trim() || 'сотрудника'}?`,
        description:
          'Сотрудник сразу перестанет входить в админку, а его текущие сессии будут закрыты. ' +
          'Учётная запись сохранится вместе с историей действий.',
        confirmLabel: 'Отключить',
      });
      if (!agreed) return;
    }
    if (!creating && withPassword) {
      const agreed = await confirm({
        title: 'Задать новый пароль?',
        description:
          'Все сессии сотрудника будут закрыты, и войти он сможет только с новым паролем. ' +
          'Передайте пароль лично.',
        confirmLabel: 'Задать пароль',
      });
      if (!agreed) return;
    }

    setSaving(true);
    setErrors({});
    try {
      if (creating) {
        const created = await usersApi.create(buildUserCreate(form));
        toast.success('Сотрудник заведён', created.email);
        onSaved(created, true);
        return;
      }
      const payload = buildUserUpdate(form, initial, { withPassword });
      if (isEmptyUpdate(payload)) {
        onClose();
        return;
      }
      const saved = await usersApi.update(user.uuid, payload);
      toast.success('Изменения сохранены', saved.email);
      onSaved(saved, false);
    } catch (error) {
      const found = userErrorsFromApi(error);
      setErrors(found);
      if (found._form) window.setTimeout(() => alertRef.current?.focus(), 0);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      variant="drawer"
      title={creating ? 'Новый сотрудник' : (user?.full_name ?? 'Сотрудник')}
      description={creating ? 'Доступ в админку по email и паролю.' : user?.email}
      busy={saving}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={saving}>
            Отмена
          </Button>
          <Button variant="primary" loading={saving} disabled={locked} onClick={() => void save()}>
            {creating ? 'Завести' : 'Сохранить'}
          </Button>
        </>
      }
    >
      <div className={styles.form}>
        {errors._form ? (
          <p className={styles.formAlert} role="alert" tabIndex={-1} ref={alertRef}>
            {errors._form}
          </p>
        ) : null}
        {locked ? (
          <p className={styles.formNote}>
            Учётной записью суперадминистратора управляет только суперадминистратор.
          </p>
        ) : null}

        {creating ? (
          <Field label="Email" required error={errors.email} hint="Служит логином.">
            <Input
              type="email"
              autoComplete="off"
              maxLength={255}
              value={form.email}
              data-autofocus
              onChange={(event) => update({ email: event.target.value })}
            />
          </Field>
        ) : (
          <Field label="Email" hint="Email неизменяем: новый адрес — новая учётная запись.">
            <p className={styles.readonlyValue}>{user?.email}</p>
          </Field>
        )}

        <Field label="Имя и фамилия" required error={errors.fullName}>
          <Input
            maxLength={255}
            value={form.fullName}
            disabled={locked}
            data-autofocus={creating ? undefined : true}
            onChange={(event) => update({ fullName: event.target.value })}
          />
        </Field>

        <div className={styles.row}>
          <Field label="Телефон" error={errors.phone}>
            <Input
              type="tel"
              maxLength={32}
              value={form.phone}
              disabled={locked}
              onChange={(event) => update({ phone: event.target.value })}
            />
          </Field>
          <Field
            label="Роль"
            required
            error={errors.role}
            hint={isSelf ? 'Свою роль изменить нельзя' : ROLE_HINTS[form.role]}
          >
            <Select
              options={roleOptions}
              value={form.role}
              disabled={locked || isSelf}
              onChange={(event) => update({ role: event.target.value as UserRole })}
            />
          </Field>
        </div>

        {selectedRole ? (
          <div>
            <p className={styles.sectionTitle}>Права роли {ROLE_LABELS[selectedRole.role]}</p>
            <ul className={styles.permissions}>
              {selectedRole.permissions.map((permission) => (
                <li key={permission}>
                  <Badge tone="neutral">{permissionLabel(permission)}</Badge>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {creating ? (
          <Field
            label="Пароль"
            required
            error={errors.password}
            hint={`Не короче ${PASSWORD_MIN_LENGTH} символов. Передайте пароль сотруднику лично.`}
          >
            <Input
              type="password"
              autoComplete="new-password"
              maxLength={512}
              value={form.password}
              onChange={(event) => update({ password: event.target.value })}
            />
          </Field>
        ) : (
          <>
            <div className={styles.divider} />
            <Switch
              label="Доступ в админку"
              description={
                isSelf
                  ? 'Отключить собственную учётную запись нельзя'
                  : 'Отключение закрывает вход и текущие сессии сразу'
              }
              checked={form.isActive}
              disabled={locked || isSelf}
              onChange={(event) => update({ isActive: event.target.checked })}
            />
            <Checkbox
              label="Задать новый пароль"
              checked={withPassword}
              disabled={locked}
              onChange={(event) => {
                setWithPassword(event.target.checked);
                if (!event.target.checked) update({ password: '' });
              }}
            />
            {withPassword ? (
              <Field
                label="Новый пароль"
                required
                error={errors.password}
                hint={`Не короче ${PASSWORD_MIN_LENGTH} символов. Все сессии сотрудника закроются.`}
              >
                <Input
                  type="password"
                  autoComplete="new-password"
                  maxLength={512}
                  value={form.password}
                  onChange={(event) => update({ password: event.target.value })}
                />
              </Field>
            ) : null}
            {user ? (
              <p className={styles.muted}>
                Заведён {formatDateTime(user.created_at)}. Последний вход{' '}
                {user.last_login_at ? formatDateTime(user.last_login_at) : 'не выполнялся'}.
              </p>
            ) : null}
          </>
        )}
      </div>
    </Dialog>
  );
}
