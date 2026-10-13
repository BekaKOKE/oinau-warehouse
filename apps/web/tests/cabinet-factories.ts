/**
 * Ответы customer API для тестов кабинета — в форме схем backend
 * (суммы и количества строками, даты ISO).
 */

import type {
  CustomerNotification,
  CustomerProfile,
  CustomerRequestDetail,
  CustomerRequestListItem,
  ProjectDetail,
  ProjectListItem,
} from '@oinau/api-types';

export function makeProfile(overrides: Partial<CustomerProfile> = {}): CustomerProfile {
  return {
    uuid: '4c1b4a8e-6f0c-4c1e-9a55-2b1f6f1d9a10',
    email: 'buyer@park-group.kz',
    contact_name: 'Айгерим',
    company_name: 'Park Group',
    phone: '+77010000000',
    region: { id: 1, code: 'almaty', name: 'Алматы' },
    email_verified_at: '2026-09-01T10:00:00Z',
    last_login_at: '2026-09-13T10:00:00Z',
    created_at: '2026-09-01T09:00:00Z',
    ...overrides,
  };
}

export function makeRequestItem(
  overrides: Partial<CustomerRequestListItem> = {},
): CustomerRequestListItem {
  return {
    number: 'R-2026-000042',
    status: 'IN_PROGRESS',
    source: 'CATALOG_CART',
    currency: 'KZT',
    total_estimate: '125000.00',
    items_count: 3,
    project: null,
    created_at: '2026-09-10T08:30:00Z',
    updated_at: '2026-09-11T08:30:00Z',
    ...overrides,
  };
}

export function makeRequestDetail(
  overrides: Partial<CustomerRequestDetail> = {},
): CustomerRequestDetail {
  return {
    ...makeRequestItem(),
    customer_name: 'Айгерим',
    phone: '+77010000000',
    email: 'buyer@park-group.kz',
    company: 'Park Group',
    region: { id: 1, code: 'almaty', name: 'Алматы' },
    comment: 'Нужна доставка до 20 сентября',
    items: [
      {
        sku: 'RP-016',
        name: 'Канат армированный Ø16 мм',
        unit: 'm',
        quantity: '50.000',
        pricing_type: 'TIERED',
        unit_price: '2500.00',
        line_total: '125000.00',
      },
    ],
    comments: [{ body: 'Счёт отправлен на почту', created_at: '2026-09-11T09:00:00Z' }],
    status_history: [
      { status: 'NEW', created_at: '2026-09-10T08:30:00Z' },
      { status: 'IN_PROGRESS', created_at: '2026-09-11T08:30:00Z' },
    ],
    ...overrides,
  };
}

export function makeProject(overrides: Partial<ProjectListItem> = {}): ProjectListItem {
  return {
    uuid: '9b2e6f40-1d6a-4a3c-8d1e-7f0a5b3c2d10',
    name: 'Площадка ЖК «Алатау»',
    status: 'ACTIVE',
    region: { id: 1, code: 'almaty', name: 'Алматы' },
    items_count: 1,
    requests_count: 0,
    created_at: '2026-09-05T08:00:00Z',
    updated_at: '2026-09-12T08:00:00Z',
    ...overrides,
  };
}

export function makeProjectDetail(overrides: Partial<ProjectDetail> = {}): ProjectDetail {
  return {
    ...makeProject(),
    description: 'Детская зона у третьего подъезда',
    items: [
      {
        sku: 'RP-016',
        name: 'Канат армированный Ø16 мм',
        slug: 'kanat-armirovannyj-16-mm',
        is_available: true,
        quantity: '40.000',
        note: null,
        added_at: '2026-09-06T08:00:00Z',
      },
    ],
    requests: [],
    ...overrides,
  };
}

export function makeNotification(
  overrides: Partial<CustomerNotification> = {},
): CustomerNotification {
  return {
    uuid: 'f1e2d3c4-b5a6-4789-9abc-def012345678',
    type: 'REQUEST_STATUS_CHANGED',
    title: 'Заявка в работе',
    message: 'Статус заявки R-2026-000042 изменён.',
    payload: { request_number: 'R-2026-000042', status: 'IN_PROGRESS' },
    is_read: false,
    read_at: null,
    created_at: '2026-09-11T08:30:00Z',
    ...overrides,
  };
}

export function page<T>(
  items: T[],
  overrides: { page?: number; pages?: number; total?: number } = {},
) {
  return {
    items,
    total: overrides.total ?? items.length,
    page: overrides.page ?? 1,
    page_size: 20,
    pages: overrides.pages ?? (items.length > 0 ? 1 : 0),
  };
}
