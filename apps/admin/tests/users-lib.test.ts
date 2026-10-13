/**
 * Сотрудники: проверка формы, тело запроса, разбор ошибок backend
 * и фильтры списка.
 */

import { describe, expect, it } from 'vitest';

import { ApiError } from '@/lib/api/client';
import {
  buildUserCreate,
  buildUserUpdate,
  EMPTY_USER_FORM,
  formFromUser,
  isEmptyUpdate,
  parseUserFilters,
  serializeUserFilters,
  userErrorsFromApi,
  userListQuery,
  validateUserForm,
  type UserForm,
} from '@/lib/users';

import { makeAdminUser } from './user-fixtures';

const filled: UserForm = {
  email: 'new@oinau-pro.kz',
  fullName: 'Айгерим Серикова',
  phone: '+7 701 000 11 22',
  role: 'MANAGER',
  password: 'another-strong-passphrase',
  isActive: true,
};

describe('проверка формы', () => {
  it('заполненная форма заведения проходит', () => {
    expect(validateUserForm(filled, { creating: true })).toEqual({});
  });

  it('требует email, имя и пароль при заведении', () => {
    const errors = validateUserForm(EMPTY_USER_FORM, { creating: true });
    expect(errors.email).toBeDefined();
    expect(errors.fullName).toBeDefined();
    expect(errors.password).toBeDefined();
  });

  it('проверяет формат email и длину пароля', () => {
    expect(validateUserForm({ ...filled, email: 'not-an-email' }, { creating: true }).email).toBe(
      'Неверный формат email',
    );
    expect(validateUserForm({ ...filled, password: 'short' }, { creating: true }).password).toMatch(
      /12/,
    );
    expect(
      validateUserForm({ ...filled, password: ' пароль с пробелом ' }, { creating: true }).password,
    ).toMatch(/Пробел/);
  });

  it('не принимает HTML в имени — это отвергнет и backend', () => {
    expect(
      validateUserForm({ ...filled, fullName: '<b>Иван</b>' }, { creating: true }).fullName,
    ).toMatch(/HTML/);
  });

  it('при правке email и пароль не обязательны', () => {
    const form = { ...filled, email: '', password: '' };
    expect(validateUserForm(form, { creating: false })).toEqual({});
    expect(validateUserForm(form, { creating: false, withPassword: true }).password).toBe(
      'Введите пароль',
    );
  });
});

describe('тело запроса', () => {
  it('заведение: пустой телефон уходит как null', () => {
    expect(buildUserCreate({ ...filled, phone: '  ' })).toEqual({
      email: 'new@oinau-pro.kz',
      full_name: 'Айгерим Серикова',
      password: 'another-strong-passphrase',
      role: 'MANAGER',
      phone: null,
    });
  });

  it('правка: только изменённые поля, email не отправляется', () => {
    const initial = formFromUser(makeAdminUser());
    const changed = { ...initial, role: 'ADMIN' as const, isActive: false };

    const payload = buildUserUpdate(changed, initial);
    expect(payload).toEqual({ role: 'ADMIN', is_active: false });
    expect(payload).not.toHaveProperty('email');
    expect(isEmptyUpdate(buildUserUpdate(initial, initial))).toBe(true);
  });

  it('пароль уходит, только когда его задали', () => {
    const initial = formFromUser(makeAdminUser());
    const withPassword = { ...initial, password: 'another-strong-passphrase' };
    expect(buildUserUpdate(withPassword, initial)).toEqual({});
    expect(buildUserUpdate(withPassword, initial, { withPassword: true })).toEqual({
      password: 'another-strong-passphrase',
    });
  });
});

describe('ошибки backend', () => {
  it('занятый email — у поля email', () => {
    const error = new ApiError(409, 'email_exists', 'Пользователь с таким email уже существует');
    expect(userErrorsFromApi(error).email).toMatch(/уже существует/);
  });

  it('правила безопасности показываются над формой', () => {
    for (const code of ['superadmin_required', 'self_deactivation', 'self_role_change']) {
      const error = new ApiError(code === 'superadmin_required' ? 403 : 409, code, 'Нельзя');
      expect(userErrorsFromApi(error)._form).toBe('Нельзя');
    }
  });

  it('422 раскладывается по полям формы', () => {
    const error = new ApiError(422, 'validation_error', 'Ошибка валидации', {
      fields: [
        { loc: ['body', 'password'], msg: 'Value error, Пароль короче 12 символов' },
        { loc: ['body', 'full_name'], msg: 'Value error, Имя не может быть пустым' },
      ],
    });
    const errors = userErrorsFromApi(error);
    expect(errors.password).toBe('Пароль короче 12 символов');
    expect(errors.fullName).toBe('Имя не может быть пустым');
  });
});

describe('фильтры списка', () => {
  it('читаются из адреса и пишутся обратно', () => {
    const filters = parseUserFilters(new URLSearchParams('search=Иван&role=ADMIN&status=disabled'));
    expect(filters).toEqual({ search: 'Иван', role: 'ADMIN', status: 'disabled', page: 1 });
    expect(new URLSearchParams(serializeUserFilters(filters))).toEqual(
      new URLSearchParams({ search: 'Иван', role: 'ADMIN', status: 'disabled' }),
    );
  });

  it('неизвестные значения отбрасываются', () => {
    expect(parseUserFilters(new URLSearchParams('role=OWNER&status=maybe'))).toEqual({
      search: '',
      role: '',
      status: '',
      page: 1,
    });
  });

  it('статус превращается в is_active, пустые фильтры не уходят', () => {
    expect(userListQuery({ search: ' ', role: '', status: 'active', page: 1 }, 24)).toEqual({
      search: undefined,
      role: undefined,
      is_active: true,
      page: 1,
      page_size: 24,
    });
    expect(
      userListQuery({ search: 'Иван', role: 'VIEWER', status: 'disabled', page: 2 }, 24),
    ).toEqual({
      search: 'Иван',
      role: 'VIEWER',
      is_active: false,
      page: 2,
      page_size: 24,
    });
  });
});
