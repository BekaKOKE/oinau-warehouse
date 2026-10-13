/**
 * Сотрудники: форма заведения и правки, фильтры списка, ошибки API.
 *
 * Матрицы прав здесь нет: состав ролей приходит из GET /admin/users/roles,
 * а решение «можно ли» всегда принимает backend. Проверки формы
 * повторяют ограничения его схем, чтобы не отправлять заведомо плохой
 * запрос, но не заменяют их.
 */

import { ApiError } from '@/lib/api/client';
import type { AdminUser, UserCreate, UserRole, UserUpdate } from '@/lib/api/types';
import { extractFieldErrors } from '@/lib/errors';
import { ROLE_LABELS } from '@/lib/auth/permissions';

/** Совпадает с PASSWORD_MIN_LENGTH backend: длина вместо «цифра и спецсимвол». */
export const PASSWORD_MIN_LENGTH = 12;

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

export const ROLE_OPTIONS: { value: UserRole; label: string }[] = (
  Object.keys(ROLE_LABELS) as UserRole[]
).map((role) => ({ value: role, label: ROLE_LABELS[role] }));

/** Короткое объяснение роли — для подсказки под селектом. */
export const ROLE_HINTS: Record<UserRole, string> = {
  SUPERADMIN: 'Полный доступ, включая API-ключи',
  ADMIN: 'Каталог, заявки, контент, сотрудники, аудит',
  CONTENT_MANAGER: 'Каталог, цены, остатки, контент сайта',
  MANAGER: 'Заявки и просмотр каталога, без изменения каталога',
  VIEWER: 'Только просмотр каталога и заявок',
};

// ----------------------------------------------------------------- форма

export type UserForm = {
  email: string;
  fullName: string;
  phone: string;
  role: UserRole;
  password: string;
  isActive: boolean;
};

export type UserFormErrors = Partial<Record<keyof UserForm | '_form', string>>;

export const EMPTY_USER_FORM: UserForm = {
  email: '',
  fullName: '',
  phone: '',
  role: 'MANAGER',
  password: '',
  isActive: true,
};

export function formFromUser(user: AdminUser): UserForm {
  return {
    email: user.email,
    fullName: user.full_name,
    phone: user.phone ?? '',
    role: user.role,
    password: '',
    isActive: user.is_active,
  };
}

type ValidateOptions = {
  /** Заведение нового сотрудника: email и пароль обязательны. */
  creating: boolean;
  /** Правка: пароль проверяется, только если его меняют. */
  withPassword?: boolean;
};

export function validateUserForm(
  form: UserForm,
  { creating, withPassword = false }: ValidateOptions,
): UserFormErrors {
  const errors: UserFormErrors = {};

  if (creating) {
    const email = form.email.trim();
    if (!email) errors.email = 'Введите email';
    else if (!EMAIL_PATTERN.test(email)) errors.email = 'Неверный формат email';
    else if (email.length > 255) errors.email = 'Не длиннее 255 символов';
  }

  const name = form.fullName.trim();
  if (!name) errors.fullName = 'Введите имя и фамилию';
  else if (name.length > 255) errors.fullName = 'Не длиннее 255 символов';
  else if (/<[/!?A-Za-z]/.test(name)) errors.fullName = 'HTML-разметка не допускается';

  if (form.phone.trim().length > 32) errors.phone = 'Не длиннее 32 символов';

  if (creating || withPassword) {
    const password = form.password;
    if (!password) errors.password = 'Введите пароль';
    else if (password.length < PASSWORD_MIN_LENGTH) {
      errors.password = `Не короче ${PASSWORD_MIN_LENGTH} символов`;
    } else if (password.trim() !== password) {
      errors.password = 'Пробел в начале или в конце недопустим';
    }
  }

  return errors;
}

export function buildUserCreate(form: UserForm): UserCreate {
  return {
    email: form.email.trim(),
    full_name: form.fullName.trim(),
    password: form.password,
    role: form.role,
    phone: form.phone.trim() || null,
  };
}

/**
 * Только изменённые поля: email в UserUpdate нет — он неизменяем.
 * Пароль уходит, лишь когда его действительно задали.
 */
export function buildUserUpdate(
  form: UserForm,
  initial: UserForm,
  { withPassword = false }: { withPassword?: boolean } = {},
): UserUpdate {
  const payload: UserUpdate = {};
  if (form.fullName.trim() !== initial.fullName.trim()) payload.full_name = form.fullName.trim();
  if (form.phone.trim() !== initial.phone.trim()) payload.phone = form.phone.trim() || null;
  if (form.role !== initial.role) payload.role = form.role;
  if (form.isActive !== initial.isActive) payload.is_active = form.isActive;
  if (withPassword && form.password) payload.password = form.password;
  return payload;
}

export function isEmptyUpdate(payload: UserUpdate): boolean {
  return Object.keys(payload).length === 0;
}

/** Ошибка backend → поле формы. Коды — из app/modules/users/exceptions.py. */
export function userErrorsFromApi(error: unknown): UserFormErrors {
  if (error instanceof ApiError) {
    if (error.code === 'email_exists') return { email: error.message };
    if (
      error.code === 'superadmin_required' ||
      error.code === 'self_deactivation' ||
      error.code === 'self_role_change' ||
      error.status === 404
    ) {
      return { _form: error.message };
    }
  }
  const map: Record<string, keyof UserFormErrors> = {
    email: 'email',
    full_name: 'fullName',
    phone: 'phone',
    role: 'role',
    password: 'password',
  };
  const result: UserFormErrors = {};
  for (const [path, message] of Object.entries(extractFieldErrors(error))) {
    const key = map[path.split('.')[0] ?? ''] ?? '_form';
    result[key] = result[key] ?? message;
  }
  if (Object.keys(result).length === 0 && error instanceof ApiError) result._form = error.message;
  return result;
}

// -------------------------------------------------------- фильтры списка

export type UserFilters = {
  search: string;
  role: UserRole | '';
  status: 'active' | 'disabled' | '';
  page: number;
};

export const DEFAULT_USER_FILTERS: UserFilters = { search: '', role: '', status: '', page: 1 };

export function parseUserFilters(params: URLSearchParams): UserFilters {
  const role = params.get('role') ?? '';
  const status = params.get('status') ?? '';
  const page = Number.parseInt(params.get('page') ?? '', 10);
  return {
    search: (params.get('search') ?? '').slice(0, 255),
    role: role in ROLE_LABELS ? (role as UserRole) : '',
    status: status === 'active' || status === 'disabled' ? status : '',
    page: Number.isFinite(page) && page > 0 ? page : 1,
  };
}

export function serializeUserFilters(filters: UserFilters): string {
  const params = new URLSearchParams();
  if (filters.search.trim()) params.set('search', filters.search.trim());
  if (filters.role) params.set('role', filters.role);
  if (filters.status) params.set('status', filters.status);
  if (filters.page > 1) params.set('page', String(filters.page));
  const query = params.toString();
  return query ? `?${query}` : '';
}

export function userListQuery(filters: UserFilters, pageSize: number) {
  return {
    search: filters.search.trim() || undefined,
    role: filters.role || undefined,
    is_active: filters.status ? filters.status === 'active' : undefined,
    page: filters.page,
    page_size: pageSize,
  };
}
