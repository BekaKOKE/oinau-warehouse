/**
 * Эндпоинты 8B: пути и параметры запросов совпадают с backend.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { auditApi, catalogApi, importsApi, stockApi, usersApi } from '@/lib/api/endpoints';
import { resetSessionForTests, storeTokens } from '@/lib/auth/session';

import { createFetchMock, fileResponse, jsonResponse, page, tokens, xlsxFile } from './helpers';

let net: ReturnType<typeof createFetchMock>;

beforeEach(() => {
  resetSessionForTests();
  net = createFetchMock();
  vi.stubGlobal('fetch', net.mock);
  storeTokens(tokens('access'));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('новые admin-эндпоинты', () => {
  it('сводка каталога', async () => {
    const summary = {
      products: { total: 1 },
      content: { without_images: 1 },
      availability: { in_stock: 0 },
      categories: { total: 2 },
    };
    net.on('GET', '/api/v1/admin/catalog/summary', summary);

    await expect(catalogApi.summary()).resolves.toEqual(summary);
  });

  it('список остатков передаёт фильтры и не отправляет пустые', async () => {
    net.on('GET', '/api/v1/admin/stock', page([]));

    await stockApi.list({ availability: 'IN_STOCK', sort: 'available_desc', search: '', page: 2 });

    const [call] = net.calls('GET', '/api/v1/admin/stock');
    const params = new URL(String(call?.[0])).searchParams;
    expect(Object.fromEntries(params)).toEqual({
      availability: 'IN_STOCK',
      sort: 'available_desc',
      page: '2',
    });
  });

  it('журнал аудита с фильтром по сущности', async () => {
    net.on('GET', '/api/v1/admin/audit', page([]));

    await auditApi.list({ entity_type: 'product', entity_id: 42, user_uuid: null });

    const [call] = net.calls('GET', '/api/v1/admin/audit');
    expect(Object.fromEntries(new URL(String(call?.[0])).searchParams)).toEqual({
      entity_type: 'product',
      entity_id: '42',
    });
  });
});

describe('импорт и экспорт каталога (8H)', () => {
  it('экспорт уходит с токеном и возвращает файл с именем', async () => {
    net.on('GET', '/api/v1/admin/catalog/export', fileResponse('PK', 'oinau-catalog.xlsx'));

    const file = await importsApi.exportCatalog();

    expect(file.filename).toBe('oinau-catalog.xlsx');
    const [call] = net.calls('GET', '/api/v1/admin/catalog/export');
    expect((call?.[1] as RequestInit).headers).toMatchObject({ Authorization: 'Bearer access' });
  });

  it('предпросмотр отправляет файл в поле file через multipart', async () => {
    net.on('POST', '/api/v1/admin/catalog/imports/preview', jsonResponse({ valid: true }));

    await importsApi.preview(xlsxFile('catalog.xlsx'));

    const [call] = net.calls('POST', '/api/v1/admin/catalog/imports/preview');
    const body = (call?.[1] as RequestInit).body as FormData;
    expect(body).toBeInstanceOf(FormData);
    expect((body.get('file') as File).name).toBe('catalog.xlsx');
    // Content-Type ставит браузер: в нём граница multipart.
    expect((call?.[1] as RequestInit).headers).not.toHaveProperty('Content-Type');
  });

  it('подтверждение идёт по uuid предпросмотра', async () => {
    const uuid = '6f1d6a2e-8a3b-4e0e-9f55-1b2c3d4e5f60';
    net.on('POST', `/api/v1/admin/catalog/imports/${uuid}/commit`, jsonResponse({}));

    await importsApi.commit(uuid, xlsxFile());

    expect(net.calls('POST', `/api/v1/admin/catalog/imports/${uuid}/commit`)).toHaveLength(1);
  });

  it('история фильтруется по статусу', async () => {
    net.on('GET', '/api/v1/admin/catalog/imports', page([]));

    await importsApi.history({ status: 'COMMITTED', page: 1, page_size: 10 });

    const [call] = net.calls('GET', '/api/v1/admin/catalog/imports');
    expect(Object.fromEntries(new URL(String(call?.[0])).searchParams)).toEqual({
      status: 'COMMITTED',
      page: '1',
      page_size: '10',
    });
  });
});

describe('сотрудники (8H)', () => {
  it('список передаёт поиск, роль и признак активности', async () => {
    net.on('GET', '/api/v1/admin/users', page([]));

    await usersApi.list({ search: 'Иван', role: 'ADMIN', is_active: false, page: 1 });

    const [call] = net.calls('GET', '/api/v1/admin/users');
    expect(Object.fromEntries(new URL(String(call?.[0])).searchParams)).toEqual({
      search: 'Иван',
      role: 'ADMIN',
      is_active: 'false',
      page: '1',
    });
  });

  it('роли читаются отдельным эндпоинтом', async () => {
    net.on('GET', '/api/v1/admin/users/roles', [{ role: 'VIEWER', permissions: ['catalog.read'] }]);

    await expect(usersApi.roles()).resolves.toEqual([
      { role: 'VIEWER', permissions: ['catalog.read'] },
    ]);
  });

  it('правка идёт PATCH по uuid', async () => {
    const uuid = 'a1b2c3d4-0000-4000-8000-000000000001';
    net.on('PATCH', `/api/v1/admin/users/${uuid}`, jsonResponse({}));

    await usersApi.update(uuid, { role: 'MANAGER' });

    const [call] = net.calls('PATCH', `/api/v1/admin/users/${uuid}`);
    expect(JSON.parse(String((call?.[1] as RequestInit).body))).toEqual({ role: 'MANAGER' });
  });
});
