/**
 * Права сотрудника в интерфейсе.
 *
 * Строки прав совпадают с `app/modules/users/permissions.py`. Список
 * прав текущего сотрудника приходит из GET /admin/auth/me — матрицу
 * «роль → права» фронтенд не хранит и по роли ничего не решает.
 *
 * ВАЖНО: скрытая кнопка — удобство, а не защита. Каждый запрос всё
 * равно проверяет backend, и 403 обрабатывается штатно.
 */

import type { UserRole } from '@/lib/api/types';

export const Permission = {
  CATALOG_READ: 'catalog.read',
  CATALOG_WRITE: 'catalog.write',
  PRICE_WRITE: 'price.write',
  STOCK_WRITE: 'stock.write',
  MEDIA_UPLOAD: 'media.upload',
  REQUEST_READ: 'request.read',
  REQUEST_WRITE: 'request.write',
  REQUEST_EXPORT: 'request.export',
  CONTENT_WRITE: 'content.write',
  USER_MANAGE: 'user.manage',
  SETTINGS_WRITE: 'settings.write',
  API_KEY_MANAGE: 'api_key.manage',
  AUDIT_READ: 'audit.read',
} as const;

export type PermissionCode = (typeof Permission)[keyof typeof Permission];

export type PermissionSet = ReadonlySet<string>;

export function hasAll(granted: PermissionSet, required: readonly PermissionCode[]): boolean {
  return required.every((permission) => granted.has(permission));
}

export const ROLE_LABELS: Record<UserRole, string> = {
  SUPERADMIN: 'Суперадминистратор',
  ADMIN: 'Администратор',
  MANAGER: 'Менеджер',
  CONTENT_MANAGER: 'Контент-менеджер',
  VIEWER: 'Наблюдатель',
};

export const PERMISSION_LABELS: Record<PermissionCode, string> = {
  'catalog.read': 'Просмотр каталога',
  'catalog.write': 'Изменение каталога',
  'price.write': 'Изменение цен',
  'stock.write': 'Изменение остатков',
  'media.upload': 'Загрузка файлов',
  'request.read': 'Просмотр заявок',
  'request.write': 'Обработка заявок',
  'request.export': 'Выгрузка заявок',
  'content.write': 'Редактирование контента',
  'user.manage': 'Управление сотрудниками',
  'settings.write': 'Настройки',
  'api_key.manage': 'API-ключи',
  'audit.read': 'Журнал аудита',
};
