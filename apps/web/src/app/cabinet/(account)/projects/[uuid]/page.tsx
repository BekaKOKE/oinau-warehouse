import type { Metadata } from 'next';

import { ProjectDetailView } from '@/components/cabinet/ProjectDetailView';

export const metadata: Metadata = { title: 'Проект' };

type Props = { params: Promise<{ uuid: string }> };

export default async function CabinetProjectPage({ params }: Props) {
  const { uuid } = await params;
  return <ProjectDetailView uuid={uuid} />;
}
