/**
 * Разделы кабинета, доступные только после входа.
 *
 * Страницы входа живут в соседней группе `(auth)` и этот каркас
 * не получают: иначе гостя с формы входа отправляло бы на вход.
 */

import type { Metadata } from 'next';
import type { ReactNode } from 'react';

import { CabinetShell } from '@/components/cabinet/CabinetShell';

// Личные страницы не индексируются, даже если ссылка на них утекла.
export const metadata: Metadata = { robots: { index: false, follow: false } };

export default function CabinetAccountLayout({ children }: { children: ReactNode }) {
  return <CabinetShell>{children}</CabinetShell>;
}
