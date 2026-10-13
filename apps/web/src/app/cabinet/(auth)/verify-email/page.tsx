/**
 * Подтверждение email по ссылке из письма.
 *
 * Backend формирует ссылку на `/account/verify-email` — этот адрес
 * перенаправляется сюда в next.config.ts вместе с токеном.
 *
 * `referrer: no-referrer` — одноразовый токен из адреса не должен
 * уйти сторонним сайтам в заголовке Referer.
 */

import type { Metadata } from 'next';

import { AuthLayout } from '@/components/cabinet/AuthLayout';
import { VerifyEmailView } from '@/components/cabinet/VerifyEmailView';
import { buildMetadata } from '@/lib/seo';

export const metadata: Metadata = {
  ...buildMetadata({
    title: 'Подтверждение email',
    description: 'Подтверждение email в личном кабинете OINAU PRO.',
    path: '/cabinet/verify-email',
    noindex: true,
  }),
  referrer: 'no-referrer',
};

type Props = { searchParams: Promise<{ token?: string | string[] }> };

export default async function VerifyEmailPage({ searchParams }: Props) {
  const { token } = await searchParams;
  return (
    <AuthLayout title="Подтверждение email">
      <VerifyEmailView token={Array.isArray(token) ? token[0] : token} />
    </AuthLayout>
  );
}
