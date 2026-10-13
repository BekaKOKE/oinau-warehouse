/**
 * CMS: тексты страниц приходят из backend, а не лежат в JSX.
 *
 * Каждая функция терпима к незаполненному разделу: сайт должен
 * открываться на пустой базе, пусть и без текстов.
 */

import type {
  ContactsContent,
  DeliveryContent,
  FaqContent,
  HomeContent,
  ServicesContent,
  SiteSettings,
} from '@oinau/api-types';

import { apiRequestOrNull } from '@/lib/api/client';

// Настройки и тексты меняются реже каталога.
const CONTENT_TTL = 300;

async function safeContent<T>(path: string): Promise<T | null> {
  try {
    return await apiRequestOrNull<T>(path, { revalidate: CONTENT_TTL });
  } catch {
    // Шапка и подвал рисуются на каждой странице. Если CMS недоступна,
    // сайт показывает значения по умолчанию, а не страницу ошибки.
    return null;
  }
}

export function fetchSiteSettings(): Promise<SiteSettings | null> {
  return safeContent<SiteSettings>('/api/v1/public/content/settings');
}

export function fetchHomeContent(): Promise<HomeContent | null> {
  return safeContent<HomeContent>('/api/v1/public/content/home');
}

export function fetchContacts(): Promise<ContactsContent | null> {
  return safeContent<ContactsContent>('/api/v1/public/content/contacts');
}

export function fetchDelivery(): Promise<DeliveryContent | null> {
  return safeContent<DeliveryContent>('/api/v1/public/content/delivery');
}

export function fetchServices(): Promise<ServicesContent | null> {
  return safeContent<ServicesContent>('/api/v1/public/content/services');
}

export function fetchFaq(): Promise<FaqContent | null> {
  return safeContent<FaqContent>('/api/v1/public/content/faq');
}
