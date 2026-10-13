/**
 * Вход, регистрация и восстановление доступа клиента — /api/v1/public/auth.
 *
 * Запросы уходят только из браузера: refresh-cookie ставится на домен
 * API, и лимиты частоты считают IP посетителя, а не сервера Next.js.
 */

import type {
  AcceptedResponse,
  CustomerLogin,
  CustomerRegister,
  CustomerTokenResponse,
} from '@oinau/api-types';

import { apiRequest } from '@/lib/api/client';
import { clearSession, storeTokens } from '@/lib/cabinet/session';

const AUTH_BASE = '/api/v1/public/auth';

export async function registerCustomer(payload: CustomerRegister): Promise<AcceptedResponse> {
  return apiRequest<AcceptedResponse>(`${AUTH_BASE}/register`, { method: 'POST', body: payload });
}

export async function verifyEmail(token: string): Promise<void> {
  await apiRequest<void>(`${AUTH_BASE}/verify-email`, { method: 'POST', body: { token } });
}

export async function resendVerification(email: string): Promise<AcceptedResponse> {
  return apiRequest<AcceptedResponse>(`${AUTH_BASE}/verify-email/resend`, {
    method: 'POST',
    body: { email },
  });
}

export async function loginCustomer(payload: CustomerLogin): Promise<CustomerTokenResponse> {
  const response = await apiRequest<CustomerTokenResponse>(`${AUTH_BASE}/login`, {
    method: 'POST',
    body: payload,
  });
  storeTokens(response);
  return response;
}

/**
 * Выход. Локальная сессия очищается в любом случае: если backend
 * недоступен, оставлять человека «вошедшим» на общем компьютере хуже,
 * чем не отозвать refresh-токен, срок которого всё равно ограничен.
 */
export async function logoutCustomer(): Promise<void> {
  try {
    await apiRequest<void>(`${AUTH_BASE}/logout`, { method: 'POST' });
  } finally {
    clearSession();
  }
}

export async function requestPasswordReset(email: string): Promise<AcceptedResponse> {
  return apiRequest<AcceptedResponse>(`${AUTH_BASE}/password-reset`, {
    method: 'POST',
    body: { email },
  });
}

export async function confirmPasswordReset(token: string, newPassword: string): Promise<void> {
  await apiRequest<void>(`${AUTH_BASE}/password-reset/confirm`, {
    method: 'POST',
    body: { token, new_password: newPassword },
  });
  // Backend отозвал все сессии — локальная тоже недействительна.
  clearSession();
}
