/**
 * Сотрудники и матрица ролей для тестов — формы из сгенерированных типов.
 */

import type { AdminUser, RolePermissions, UserRole } from '@/lib/api/types';

import { ROLE_PERMISSIONS } from './helpers';

export const USERS_URL = '/api/v1/admin/users';
export const ROLES_URL = '/api/v1/admin/users/roles';

/** uuid вошедшего сотрудника из makeUser(): нужен для «это вы». */
export const SELF_UUID = '6f1d6a2e-8a3b-4e0e-9f55-1b2c3d4e5f60';

export function makeAdminUser(overrides: Partial<AdminUser> = {}): AdminUser {
  return {
    uuid: 'a1b2c3d4-0000-4000-8000-000000000001',
    email: 'manager@oinau-pro.kz',
    full_name: 'Бекзат Оспанов',
    phone: '+7 701 555 12 34',
    role: 'MANAGER',
    is_active: true,
    last_login_at: '2026-09-16T05:00:00Z',
    created_at: '2026-09-01T08:00:00Z',
    updated_at: '2026-09-16T05:00:00Z',
    ...overrides,
  };
}

export const USER_ROWS: AdminUser[] = [
  makeAdminUser(),
  makeAdminUser({
    uuid: 'a1b2c3d4-0000-4000-8000-000000000002',
    email: 'content@oinau-pro.kz',
    full_name: 'Жанна Ахметова',
    role: 'CONTENT_MANAGER',
    phone: null,
    last_login_at: null,
  }),
  makeAdminUser({
    uuid: 'a1b2c3d4-0000-4000-8000-000000000003',
    email: 'viewer@oinau-pro.kz',
    full_name: 'Пётр Кузнецов',
    role: 'VIEWER',
    is_active: false,
  }),
];

export const ROLES: RolePermissions[] = (Object.keys(ROLE_PERMISSIONS) as UserRole[]).map(
  (role) => ({ role, permissions: [...ROLE_PERMISSIONS[role]].sort() }),
);
