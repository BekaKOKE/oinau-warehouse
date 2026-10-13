/**
 * Журнал аудита: фильтры, подписи и разбор `changes` — без DOM.
 */

import { describe, expect, it } from 'vitest';

import {
  auditActionLabel,
  auditActionTone,
  auditActorLabel,
  auditDateRangeError,
  auditEntityHref,
  auditEntityLabel,
  auditListQuery,
  actionOptions,
  changeRows,
  changesSummary,
  DEFAULT_AUDIT_FILTERS,
  hasActiveAuditFilters,
  isSecretKey,
  parseAuditFilters,
  serializeAuditFilters,
} from '@/lib/audit';

import { makeAuditEntry } from './audit-fixtures';

describe('подписи', () => {
  it('известное действие переводится, неизвестное показывается кодом', () => {
    expect(auditActionLabel('catalog.product_created')).toBe('Товар создан');
    expect(auditActionLabel('telegram.message_sent')).toBe('telegram.message_sent');
    expect(auditActionTone('catalog.product_deleted')).toBe('danger');
    expect(auditActionTone('telegram.message_sent')).toBe('neutral');
  });

  it('раздел и источник тоже переживают неизвестное значение', () => {
    expect(auditEntityLabel('product_pricing')).toBe('Цены товара');
    expect(auditEntityLabel('notification')).toBe('notification');
    expect(auditActorLabel('import')).toBe('Импорт из файла');
    expect(auditActorLabel('robot')).toBe('robot');
  });

  it('выбор раздела сужает список действий', () => {
    const forRequests = actionOptions('request').map((option) => option.value);
    expect(forRequests).toContain('request.status_updated');
    expect(forRequests).not.toContain('catalog.product_created');
    // Без раздела доступны все действия.
    expect(actionOptions('').length).toBeGreaterThan(forRequests.length);
  });
});

describe('ссылки на объект', () => {
  it('ведут туда, где объект открывается по числовому id', () => {
    expect(auditEntityHref(makeAuditEntry({ entity_type: 'product', entity_id: 42 }))).toBe(
      '/products/42',
    );
    expect(auditEntityHref(makeAuditEntry({ entity_type: 'product_stock', entity_id: 42 }))).toBe(
      '/products/42',
    );
    expect(auditEntityHref(makeAuditEntry({ entity_type: 'request', entity_id: 7 }))).toBe(
      '/requests/7',
    );
    expect(auditEntityHref(makeAuditEntry({ entity_type: 'category', entity_id: 3 }))).toBe(
      '/categories?id=3',
    );
  });

  it('нет ссылки там, где адрес строится по uuid или объекта нет', () => {
    // У файла, импорта и сотрудника адрес админки — по uuid, его в журнале нет.
    expect(auditEntityHref(makeAuditEntry({ entity_type: 'media_file', entity_id: 5 }))).toBeNull();
    expect(auditEntityHref(makeAuditEntry({ entity_type: 'user', entity_id: 1 }))).toBeNull();
    expect(auditEntityHref(makeAuditEntry({ entity_type: 'product', entity_id: null }))).toBeNull();
  });
});

describe('изменения', () => {
  it('пара old/new разбирается в «было → стало», остальное — значением', () => {
    const rows = changeRows({ status: { old: 'DRAFT', new: 'PUBLISHED' }, rows_total: 151 });
    expect(rows[0]).toMatchObject({ label: 'Статус', before: 'DRAFT', after: 'PUBLISHED' });
    expect(rows[1]).toMatchObject({ label: 'Строк в файле', value: '151' });
  });

  it('null, логическое и вложенное значение читаются человеком', () => {
    const rows = changeRows({ parent_id: null, is_active: true, products: { create: 2 } });
    expect(rows[0]?.value).toBe('—');
    expect(rows[1]?.value).toBe('да');
    expect(rows[2]?.value).toContain('"create": 2');
  });

  it('секретные ключи скрываются, даже если backend их пришлёт', () => {
    expect(isSecretKey('password')).toBe(true);
    expect(isSecretKey('password_hash')).toBe(true);
    expect(isSecretKey('storage_key')).toBe(true);
    expect(isSecretKey('ip_hash')).toBe(true);
    expect(isSecretKey('file_sha256')).toBe(false);

    const rows = changeRows({ password: 'p@ssw0rd', role: 'ADMIN' });
    expect(rows[0]).toMatchObject({ secret: true, value: 'скрыто' });
    expect(rows[1]?.value).toBe('ADMIN');
  });

  it('сводка перечисляет поля и не растёт бесконечно', () => {
    expect(changesSummary({})).toBe('');
    expect(changesSummary({ status: 1, price: 2 })).toBe('Статус, Цена');
    expect(changesSummary({ a: 1, b: 2, c: 3, d: 4, e: 5 })).toBe('a, b, c и ещё 2');
  });
});

describe('фильтры', () => {
  it('разбирает адрес и отбрасывает мусор', () => {
    const filters = parseAuditFilters(
      new URLSearchParams('action=user.created&entity=user&entity_id=abc&user=not-a-uuid&page=0'),
    );
    expect(filters).toMatchObject({
      action: 'user.created',
      entityType: 'user',
      entityId: '',
      userUuid: '',
      page: 1,
    });
  });

  it('пустые фильтры не попадают в адрес', () => {
    expect(serializeAuditFilters(DEFAULT_AUDIT_FILTERS)).toBe('');
    expect(hasActiveAuditFilters(DEFAULT_AUDIT_FILTERS)).toBe(false);
    expect(serializeAuditFilters({ ...DEFAULT_AUDIT_FILTERS, actor: 'import', page: 3 })).toBe(
      '?actor=import&page=3',
    );
  });

  it('период уходит границами суток Алматы полуинтервалом', () => {
    const query = auditListQuery({
      ...DEFAULT_AUDIT_FILTERS,
      dateFrom: '2026-09-17',
      dateTo: '2026-09-17',
    });
    expect(query.created_from).toBe('2026-09-17T00:00:00+05:00');
    // Граница «по» — начало следующего дня, исключительно.
    expect(query.created_to).toBe('2026-09-18T00:00:00+05:00');
    expect(query.page_size).toBe(30);
  });

  it('обратный период распознаётся до запроса', () => {
    expect(auditDateRangeError(DEFAULT_AUDIT_FILTERS)).toBeNull();
    expect(
      auditDateRangeError({
        ...DEFAULT_AUDIT_FILTERS,
        dateFrom: '2026-09-18',
        dateTo: '2026-09-01',
      }),
    ).toBe('Дата «с» позже даты «по»');
  });

  it('пустые значения не превращаются в параметры запроса', () => {
    const query = auditListQuery(DEFAULT_AUDIT_FILTERS);
    expect(query.action).toBeUndefined();
    expect(query.entity_type).toBeUndefined();
    expect(query.entity_id).toBeUndefined();
    expect(query.user_uuid).toBeUndefined();
    expect(query.created_from).toBeUndefined();
  });
});
