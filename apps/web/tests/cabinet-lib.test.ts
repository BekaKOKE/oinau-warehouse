/**
 * Чистые функции кабинета: адрес возврата после входа, статусы,
 * суммы и разбор ошибок backend.
 */

import { describe, expect, it } from 'vitest';

import { ApiError } from '@oinau/api-client';

import {
  describeCabinetError,
  describeRequestStatus,
  fieldErrorsFrom,
  formatMoney,
  formatUnitPrice,
  isUnauthenticated,
  validatePassword,
  validatePhone,
} from '@/lib/cabinet/format';
import {
  isCabinetNavActive,
  loginHref,
  pageFromQuery,
  safeNextPath,
} from '@/lib/cabinet/navigation';
import { UnauthenticatedError } from '@/lib/cabinet/session';

describe('safeNextPath', () => {
  it.each([
    ['/cabinet/requests', '/cabinet/requests'],
    ['/cabinet/requests/R-2026-000001', '/cabinet/requests/R-2026-000001'],
    ['/cabinet/notifications?unread=1', '/cabinet/notifications?unread=1'],
  ])('пропускает путь кабинета %s', (value, expected) => {
    expect(safeNextPath(value)).toBe(expected);
  });

  it.each([
    'https://evil.example/cabinet',
    '//evil.example/cabinet',
    '/\\evil.example',
    '/admin',
    '/cabinetevil',
    '/cabinet/login',
    'javascript:alert(1)',
    '',
    undefined,
  ])('не допускает открытый редирект: %s', (value) => {
    expect(safeNextPath(value)).toBe('/cabinet');
  });

  it('loginHref добавляет next только для внутренних страниц', () => {
    expect(loginHref('/cabinet')).toBe('/cabinet/login');
    expect(loginHref('/cabinet/projects')).toBe('/cabinet/login?next=%2Fcabinet%2Fprojects');
    expect(loginHref('https://evil.example')).toBe('/cabinet/login');
  });
});

describe('навигация кабинета', () => {
  it('«Обзор» активен только на /cabinet', () => {
    expect(isCabinetNavActive('/cabinet', '/cabinet')).toBe(true);
    expect(isCabinetNavActive('/cabinet/requests', '/cabinet')).toBe(false);
    expect(isCabinetNavActive('/cabinet/requests/R-1', '/cabinet/requests')).toBe(true);
  });

  it.each([
    [undefined, 1],
    ['3', 3],
    ['0', 1],
    ['-2', 1],
    ['abc', 1],
    ['2.5', 1],
  ])('pageFromQuery(%s) = %s', (value, expected) => {
    expect(pageFromQuery(value)).toBe(expected);
  });
});

describe('форматирование', () => {
  it('SPAM backend не отдаёт, а неизвестный статус не ломает экран', () => {
    expect(describeRequestStatus('CANCELLED').label).toBe('Отменена');
    expect(describeRequestStatus('WAITING_CLIENT').tone).toBe('warning');
    expect(describeRequestStatus('UNKNOWN' as never).label).toBe('UNKNOWN');
  });

  it('сумма без значения — «По запросу», а не ноль', () => {
    expect(formatMoney(null, 'KZT')).toBe('По запросу');
    expect(formatMoney('125000.00', 'KZT')).toMatch(/125\s000 ₸/);
    expect(formatUnitPrice('3500.00', 'KZT', 'ON_REQUEST')).toBe('По запросу');
  });

  it('проверка пароля совпадает с правилами backend', () => {
    expect(validatePassword('short')).toMatch(/12/);
    expect(validatePassword(' customer-strong ')).toMatch(/пробел/);
    expect(validatePassword('customer-strong-password')).toBeUndefined();
  });

  it('проверка телефона', () => {
    expect(validatePhone('+7 (700) 000-00-00')).toBeUndefined();
    expect(validatePhone('12')).toMatch(/от 5 до 15/);
    expect(validatePhone('+7 700 abc 00 00')).toMatch(/только цифры/);
  });
});

describe('ошибки', () => {
  it('разбирает validation_error в ошибки полей без префикса Pydantic', () => {
    const error = new ApiError(422, 'validation_error', 'Ошибка валидации', {
      fields: [
        {
          loc: ['body', 'phone'],
          msg: 'Value error, В номере телефона должно быть от 5 до 15 цифр',
        },
        { loc: ['body', 'password'], msg: 'Value error, Пароль короче 12 символов' },
      ],
    });
    expect(fieldErrorsFrom(error)).toEqual({
      phone: 'В номере телефона должно быть от 5 до 15 цифр',
      password: 'Пароль короче 12 символов',
    });
    expect(fieldErrorsFrom(new Error('x'))).toEqual({});
  });

  it('понятные тексты для лимита, 401 и 403', () => {
    expect(describeCabinetError(new ApiError(429, 'rate_limited', 'Too many'))).toMatch(
      /Слишком много попыток/,
    );
    expect(describeCabinetError(new UnauthenticatedError())).toMatch(/Войдите/);
    expect(describeCabinetError(new ApiError(403, 'forbidden', 'Forbidden'))).toMatch(/прав/);
    expect(
      describeCabinetError(new ApiError(401, 'invalid_credentials', 'Неверный email или пароль')),
    ).toBe('Неверный email или пароль');
    expect(
      describeCabinetError(new ApiError(403, 'account_locked', 'Учётная запись заблокирована')),
    ).toBe('Учётная запись заблокирована');
  });

  it('isUnauthenticated', () => {
    expect(isUnauthenticated(new UnauthenticatedError())).toBe(true);
    expect(isUnauthenticated(new ApiError(401, 'x', 'x'))).toBe(true);
    expect(isUnauthenticated(new ApiError(404, 'x', 'x'))).toBe(false);
  });
});
