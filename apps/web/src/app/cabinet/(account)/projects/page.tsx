import type { Metadata } from 'next';

import { ProjectsList } from '@/components/cabinet/ProjectsList';
import { pageFromQuery } from '@/lib/cabinet/navigation';

export const metadata: Metadata = { title: 'Проекты' };

type Props = { searchParams: Promise<{ page?: string | string[]; create?: string }> };

export default async function CabinetProjectsPage({ searchParams }: Props) {
  const { page, create } = await searchParams;
  return <ProjectsList page={pageFromQuery(page)} openCreate={create === '1'} />;
}
