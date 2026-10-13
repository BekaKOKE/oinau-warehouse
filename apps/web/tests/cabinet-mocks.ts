/**
 * Общие подмены для тестов кабинета.
 *
 * API кабинета подменяется на уровне модулей `lib/api/*`: компоненты
 * проверяются вместе с провайдерами сессии, избранного и уведомлений,
 * а сеть не нужна. Состояние сессии управляется `sessionState`.
 *
 * Модуль не импортирует код приложения: фабрики `vi.mock` подгружают его
 * динамически, и импорт компонентов отсюда дал бы цикл.
 */

import { vi } from 'vitest';

import { makeProfile, page } from './cabinet-factories';

export const sessionState: { hint: boolean; token: string | null } = { hint: false, token: null };

export const customerApi = {
  fetchProfile: vi.fn(),
  updateProfile: vi.fn(),
  fetchFavorites: vi.fn(),
  fetchAllFavoriteSkus: vi.fn(),
  addFavorite: vi.fn(),
  removeFavorite: vi.fn(),
  fetchCustomerRequests: vi.fn(),
  fetchCustomerRequest: vi.fn(),
  submitCustomerRequest: vi.fn(),
  fetchProjects: vi.fn(),
  fetchProject: vi.fn(),
  createProject: vi.fn(),
  updateProject: vi.fn(),
  deleteProject: vi.fn(),
  addProjectItem: vi.fn(),
  removeProjectItem: vi.fn(),
  fetchNotifications: vi.fn(),
  fetchUnreadCount: vi.fn(),
  markNotificationRead: vi.fn(),
  markAllNotificationsRead: vi.fn(),
};

export const authApi = {
  registerCustomer: vi.fn(),
  verifyEmail: vi.fn(),
  resendVerification: vi.fn(),
  loginCustomer: vi.fn(),
  logoutCustomer: vi.fn(),
  requestPasswordReset: vi.fn(),
  confirmPasswordReset: vi.fn(),
};

export const regionsApi = { fetchRegions: vi.fn(), submitRequest: vi.fn() };

export const catalogApi = { fetchProduct: vi.fn() };

/** Настройки по умолчанию: пустой кабинет и два региона. */
export function resetCabinetMocks() {
  sessionState.hint = false;
  sessionState.token = null;
  for (const mock of [...Object.values(customerApi), ...Object.values(authApi)]) {
    mock.mockReset();
  }
  customerApi.fetchProfile.mockResolvedValue(makeProfile());
  customerApi.fetchAllFavoriteSkus.mockResolvedValue([]);
  customerApi.fetchFavorites.mockResolvedValue(page([]));
  customerApi.fetchUnreadCount.mockResolvedValue({ unread: 0 });
  customerApi.fetchCustomerRequests.mockResolvedValue(page([]));
  customerApi.fetchProjects.mockResolvedValue(page([]));
  customerApi.fetchNotifications.mockResolvedValue(page([]));
  authApi.logoutCustomer.mockResolvedValue(undefined);
  regionsApi.fetchRegions.mockReset();
  regionsApi.fetchRegions.mockResolvedValue([
    { id: 1, code: 'almaty', name: 'Алматы' },
    { id: 2, code: 'astana', name: 'Астана' },
  ]);
  regionsApi.submitRequest.mockReset();
  catalogApi.fetchProduct.mockReset();
  catalogApi.fetchProduct.mockResolvedValue(null);
}

export function signIn() {
  sessionState.hint = true;
  sessionState.token = 'access-token';
}
