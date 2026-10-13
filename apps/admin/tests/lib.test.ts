/**
 * Чистые функции: даты, склонения, ошибки API, навигация по правам.
 */

import { ApiError } from '@oinau/api-client';
import { describe, expect, it } from 'vitest';

import { NetworkError } from '@/lib/api/client';
import { UnauthenticatedError } from '@/lib/auth/session';
import { describeError, extractFieldErrors } from '@/lib/errors';
import { formatDateTime, formatRelative, plural } from '@/lib/format';
import { enumOptions, REQUEST_STATUS } from '@/lib/labels';
import { safeNextPath, visibleNav } from '@/lib/navigation';

import { ROLE_PERMISSIONS } from './helpers';

describe('даты', () => {
  it('показывает время в Asia/Almaty независимо от пояса компьютера', () => {
    expect(formatDateTime('2026-09-14T03:30:00Z')).toBe('14.09.2026, 08:30');
  });

  it('относительное время для свежих событий', () => {
    const now = new Date('2026-09-14T10:00:00Z');
    expect(formatRelative('2026-09-14T09:59:40Z', now)).toBe('только что');
    expect(formatRelative('2026-09-14T09:15:00Z', now)).toBe('45 мин назад');
    expect(formatRelative('2026-09-14T07:00:00Z', now)).toBe('3 ч назад');
  });

  it('склонения', () => {
    expect(plural(1, ['заявка', 'заявки', 'заявок'])).toBe('заявка');
    expect(plural(3, ['заявка', 'заявки', 'заявок'])).toBe('заявки');
    expect(plural(11, ['заявка', 'заявки', 'заявок'])).toBe('заявок');
    expect(plural(22, ['заявка', 'заявки', 'заявок'])).toBe('заявки');
  });
});

describe('ошибки API', () => {
  const validation = new ApiError(422, 'validation_error', 'Ошибка валидации входных данных', {
    fields: [
      { loc: ['body', 'translations', 'ru', 'name'], msg: 'Field required' },
      { loc: ['body'], msg: 'Value error, Для типа FIXED должна быть ровно одна ступень' },
    ],
  });

  it('раскладывает 422 по полям и убирает служебную приставку Pydantic', () => {
    expect(extractFieldErrors(validation)).toEqual({
      'translations.ru.name': 'Field required',
      _form: 'Для типа FIXED должна быть ровно одна ступень',
    });
  });

  it('человеческие тексты для 403, 429, 5xx, сети и истёкшей сессии', () => {
    expect(describeError(new ApiError(403, 'permission_denied', 'Недостаточно прав'))).toMatch(
      /прав/,
    );
    expect(describeError(new ApiError(429, 'rate_limited', 'x'))).toMatch(/Слишком много/);
    expect(describeError(new ApiError(500, 'internal_error', 'x', undefined, 'abc123'))).toContain(
      'abc123',
    );
    expect(describeError(new NetworkError())).toMatch(/Нет связи/);
    expect(describeError(new UnauthenticatedError())).toMatch(/Войдите/);
  });

  it('сообщение бизнес-ошибки backend показывается как есть', () => {
    expect(describeError(new ApiError(409, 'conflict', 'Артикул уже занят'))).toBe(
      'Артикул уже занят',
    );
  });
});

describe('навигация по правам', () => {
  const hrefs = (role: keyof typeof ROLE_PERMISSIONS) =>
    visibleNav(new Set(ROLE_PERMISSIONS[role])).flatMap((group) =>
      group.items.map((item) => item.href),
    );

  it('менеджер видит заявки и каталог только для чтения, без управления каталогом', () => {
    // Импорт/экспорт открыт с catalog.read: выгрузить каталог и проверить
    // файл backend позволяет и без права записи (применить — нет).
    expect(hrefs('MANAGER')).toEqual(['/', '/requests', '/products', '/stock', '/import-export']);
  });

  it('контент-менеджер не видит заявки, пользователей и аудит', () => {
    const items = hrefs('CONTENT_MANAGER');
    expect(items).toContain('/content');
    expect(items).toContain('/import-export');
    expect(items).not.toContain('/requests');
    expect(items).not.toContain('/users');
    expect(items).not.toContain('/audit');
  });

  it('администратор видит все разделы', () => {
    expect(hrefs('ADMIN')).toEqual([
      '/',
      '/requests',
      '/products',
      '/categories',
      '/attributes',
      '/colors',
      '/stock',
      '/import-export',
      '/content',
      '/users',
      '/audit',
      '/integration',
    ]);
  });

  it('наблюдатель — только чтение каталога и заявок', () => {
    expect(hrefs('VIEWER')).toEqual(['/', '/requests', '/products', '/stock', '/import-export']);
  });

  it('после входа возвращает только на внутренний путь', () => {
    expect(safeNextPath('/requests?status=NEW')).toBe('/requests?status=NEW');
    expect(safeNextPath('//evil.example/phish')).toBe('/');
    expect(safeNextPath('https://evil.example')).toBe('/');
    expect(safeNextPath('/\\evil.example')).toBe('/');
    expect(safeNextPath('/login')).toBe('/');
    expect(safeNextPath(null)).toBe('/');
  });
});

describe('перечисления', () => {
  it('варианты статусов заявок — все значения backend в порядке объявления', () => {
    expect(enumOptions(REQUEST_STATUS).map((option) => option.value)).toEqual([
      'NEW',
      'IN_PROGRESS',
      'WAITING_CLIENT',
      'QUOTE_SENT',
      'APPROVED',
      'COMPLETED',
      'CANCELLED',
      'SPAM',
    ]);
  });
});
