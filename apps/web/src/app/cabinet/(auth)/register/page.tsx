import type { Metadata } from 'next';
import Link from 'next/link';

import { AuthLayout } from '@/components/cabinet/AuthLayout';
import { RegisterForm } from '@/components/cabinet/RegisterForm';
import { buildMetadata } from '@/lib/seo';

export const metadata: Metadata = buildMetadata({
  title: 'Регистрация',
  description: 'Регистрация в личном кабинете клиента OINAU PRO.',
  path: '/cabinet/register',
  noindex: true,
});

export default function CabinetRegisterPage() {
  return (
    <AuthLayout
      wide
      title="Регистрация"
      lead="После регистрации подтвердите email по ссылке из письма — затем можно войти."
      footer={
        <>
          Уже есть аккаунт? <Link href="/cabinet/login">Войти</Link>
        </>
      }
    >
      <RegisterForm />
    </AuthLayout>
  );
}
