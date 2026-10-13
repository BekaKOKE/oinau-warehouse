/**
 * Восстановление пароля: без токена — запрос ссылки, с токеном из
 * письма — установка нового пароля.
 *
 * Ссылка backend (`/account/reset-password`) перенаправляется сюда
 * в next.config.ts.
 */

import type { Metadata } from 'next';
import Link from 'next/link';

import { AuthLayout } from '@/components/cabinet/AuthLayout';
import { ResetPasswordView } from '@/components/cabinet/ResetPasswordView';
import { buildMetadata } from '@/lib/seo';

export const metadata: Metadata = {
  ...buildMetadata({
    title: 'Восстановление пароля',
    description: 'Восстановление доступа к личному кабинету OINAU PRO.',
    path: '/cabinet/reset-password',
    noindex: true,
  }),
  referrer: 'no-referrer',
};

type Props = { searchParams: Promise<{ token?: string | string[] }> };

export default async function ResetPasswordPage({ searchParams }: Props) {
  const raw = (await searchParams).token;
  const token = Array.isArray(raw) ? raw[0] : raw;
  return (
    <AuthLayout
      title={token ? 'Новый пароль' : 'Восстановление пароля'}
      lead={
        token
          ? 'Придумайте новый пароль. После сохранения все прежние сессии будут завершены.'
          : 'Укажите email аккаунта — отправим ссылку для установки нового пароля.'
      }
      footer={<Link href="/cabinet/login">Вернуться ко входу</Link>}
    >
      <ResetPasswordView token={token} />
    </AuthLayout>
  );
}
