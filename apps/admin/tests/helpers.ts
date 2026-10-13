/**
 * Подмена сети и фабрики данных для тестов.
 *
 * Ответы описываются маршрутами «метод + путь»: тест видит, какие
 * запросы реально ушли на backend, с какими заголовками и параметрами.
 */

import { vi } from 'vitest';

import type { CurrentUser, RequestDetail, RequestListItem, UserRole } from '@/lib/api/types';

export function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: 'status',
    json: async () => body,
  } as Response;
}

export function errorResponse(status: number, code: string, message: string, details?: unknown) {
  return jsonResponse({ error: { code, message, details, request_id: 'req-test' } }, status);
}

/**
 * Ответ-файл: у него есть заголовки и blob(), которых нет у jsonResponse.
 * Так отвечает backend на экспорт XLSX.
 */
export function fileResponse(content: string, filename?: string, status = 200): Response {
  const headers = new Map<string, string>();
  if (filename) headers.set('content-disposition', `attachment; filename="${filename}"`);
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: 'status',
    headers: { get: (name: string) => headers.get(name.toLowerCase()) ?? null },
    blob: async () => new Blob([content]),
    json: async () => ({}),
  } as unknown as Response;
}

/** Файл .xlsx для поля выбора файла. */
export function xlsxFile(name = 'catalog.xlsx', size = 2048): File {
  const file = new File(['x'], name, {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
  Object.defineProperty(file, 'size', { value: size });
  return file;
}

export const tokens = (token: string, expiresIn = 900) => ({
  access_token: token,
  token_type: 'bearer',
  expires_in: expiresIn,
});

function isResponse(value: unknown): value is Response {
  return typeof value === 'object' && value !== null && 'status' in value && 'json' in value;
}

type Handler = (url: URL, init: RequestInit) => Response | Promise<Response>;

export function createFetchMock() {
  const routes = new Map<string, Handler>();
  const mock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input));
    const method = (init.method ?? 'GET').toUpperCase();
    const handler = routes.get(`${method} ${url.pathname}`);
    if (!handler) return errorResponse(404, 'not_found', `Нет маршрута ${method} ${url.pathname}`);
    return handler(url, init);
  });

  return {
    mock,
    on(method: string, path: string, handler: Handler | Response | unknown) {
      routes.set(
        `${method} ${path}`,
        typeof handler === 'function'
          ? (handler as Handler)
          : () => (isResponse(handler) ? handler : jsonResponse(handler)),
      );
    },
    calls(method: string, path: string) {
      return mock.mock.calls.filter(
        ([input, init]) =>
          new URL(String(input)).pathname === path &&
          ((init as RequestInit | undefined)?.method ?? 'GET').toUpperCase() === method,
      );
    },
  };
}

export function authHeader(call: unknown[]): string | undefined {
  return ((call[1] as RequestInit).headers as Record<string, string>).Authorization;
}

/**
 * Права ролей для тестов интерфейса — копия матрицы backend
 * (app/modules/users/permissions.py). В самом приложении матрицы нет:
 * права приходят из /auth/me.
 */
const CONTENT_MANAGER = [
  'catalog.read',
  'catalog.write',
  'price.write',
  'stock.write',
  'media.upload',
  'content.write',
];
const MANAGER = ['catalog.read', 'request.read', 'request.write', 'request.export'];
const ADMIN = [...CONTENT_MANAGER, ...MANAGER, 'user.manage', 'settings.write', 'audit.read'];

export const ROLE_PERMISSIONS: Record<UserRole, string[]> = {
  SUPERADMIN: [...ADMIN, 'api_key.manage'],
  ADMIN,
  MANAGER,
  CONTENT_MANAGER,
  VIEWER: ['catalog.read', 'request.read'],
};

export function makeUser(role: UserRole, overrides: Partial<CurrentUser> = {}): CurrentUser {
  return {
    uuid: '6f1d6a2e-8a3b-4e0e-9f55-1b2c3d4e5f60',
    email: 'staff@oinau-pro.kz',
    full_name: 'Айгерим Серикова',
    phone: null,
    role,
    is_active: true,
    last_login_at: null,
    created_at: '2026-09-01T08:00:00Z',
    updated_at: '2026-09-01T08:00:00Z',
    permissions: [...ROLE_PERMISSIONS[role]].sort(),
    ...overrides,
  };
}

export function page<T>(items: T[], total = items.length) {
  return { items, total, page: 1, page_size: 24, pages: total ? Math.ceil(total / 24) : 0 };
}

type FetchMock = ReturnType<typeof createFetchMock>;

/** Сотрудник с ролью «вошёл»: признак сессии, refresh и профиль. */
export function signInAs(net: FetchMock, role: UserRole) {
  window.localStorage.setItem('oinau.admin.session', '1');
  net.on('POST', '/api/v1/admin/auth/refresh', tokens('access'));
  net.on('GET', '/api/v1/admin/auth/me', makeUser(role));
}

export function makeRequestListItem(overrides: Partial<RequestListItem> = {}): RequestListItem {
  return {
    id: 1,
    number: 'R-2026-000001',
    kind: 'CART',
    source: 'CATALOG_CART',
    status: 'NEW',
    customer_name: 'Нурлан Бекенов',
    phone: '+7 777 210 44 18',
    email: 'nurlan@park.kz',
    company: 'ТОО «Детские площадки KZ»',
    region: { id: 1, code: 'almaty', name: 'Алматы' },
    items_count: 2,
    total_estimate: '520200.00',
    currency: 'KZT',
    created_at: '2026-09-14T03:30:00Z',
    updated_at: '2026-09-14T03:30:00Z',
    ...overrides,
  };
}

export function makeRequestDetail(overrides: Partial<RequestDetail> = {}): RequestDetail {
  return {
    id: 7,
    uuid: '0b0f5c7e-6d7b-4d4e-9d3f-3d7c1c7a9a11',
    number: 'R-2026-000007',
    kind: 'CART',
    status: 'NEW',
    source: 'CATALOG_CART',
    customer_name: 'Айгерим Сапарова',
    phone: '+7 701 555 12 34',
    email: 'a.saparova@park-group.kz',
    company: 'Park Group',
    region: { id: 1, code: 'almaty', name: 'Алматы' },
    comment: 'Нужен счёт и сроки поставки',
    currency: 'KZT',
    total_estimate: '152500.50',
    items: [
      {
        id: 11,
        product_id: 5,
        sku: 'KAN-16-PP',
        name: 'Канат полипропиленовый 16 мм',
        unit: 'm',
        pricing_type: 'TIERED',
        quantity: '50.000',
        unit_price: '3050.01',
        line_total: '152500.50',
        color: 'red',
        color_name: 'Красный',
      },
      {
        id: 12,
        product_id: null,
        sku: 'SID-01',
        name: 'Сиденье качелей HDPE',
        unit: 'pcs',
        pricing_type: 'ON_REQUEST',
        quantity: '4.000',
        unit_price: null,
        line_total: null,
      },
    ],
    comments: [
      {
        id: 21,
        body: 'Перезвонить после обеда',
        is_internal: true,
        author: { uuid: '6f1d6a2e-8a3b-4e0e-9f55-1b2c3d4e5f60', full_name: 'Данияр Ахметов' },
        created_at: '2026-09-14T04:00:00Z',
      },
      {
        id: 22,
        body: 'Счёт отправили на почту',
        is_internal: false,
        author: { uuid: '6f1d6a2e-8a3b-4e0e-9f55-1b2c3d4e5f60', full_name: 'Данияр Ахметов' },
        created_at: '2026-09-14T05:00:00Z',
      },
    ],
    status_history: [
      {
        id: 31,
        from_status: null,
        to_status: 'NEW',
        comment: null,
        changed_by: null,
        created_at: '2026-09-14T03:30:00Z',
      },
    ],
    created_at: '2026-09-14T03:30:00Z',
    updated_at: '2026-09-14T05:00:00Z',
    ...overrides,
  };
}
