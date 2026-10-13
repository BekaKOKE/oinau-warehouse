/**
 * Вход в личный кабинет.
 *
 * `next` — куда вернуть после входа; проверяется в `safeNextPath`,
 * чтобы форма не стала открытым редиректом.
 */

import type { Metadata } from 'next';
import Link from 'next/link';

import { AuthLayout } from '@/components/cabinet/AuthLayout';
import { LoginForm } from '@/components/cabinet/LoginForm';
import { buildMetadata } from '@/lib/seo';

export const metadata: Metadata = buildMetadata({
  title: 'Вход в кабинет',
  description: 'Вход в личный кабинет клиента OINAU PRO.',
  path: '/cabinet/login',
  noindex: true,
});

type Props = { searchParams: Promise<{ next?: string | string[] }> };

export default async function CabinetLoginPage({ searchParams }: Props) {
  const { next } = await searchParams;
  return (
    <AuthLayout
      title="Вход в кабинет"
      lead="История заявок, проекты и избранное — в одном аккаунте."
      footer={
        <>
          Нет аккаунта? <Link href="/cabinet/register">Зарегистрироваться</Link>
        </>
      }
    >
      <LoginForm next={Array.isArray(next) ? next[0] : next} />
    </AuthLayout>
  );
}
