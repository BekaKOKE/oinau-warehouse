import type { Metadata } from 'next';

import { RequestsList } from '@/components/cabinet/RequestsList';
import { pageFromQuery } from '@/lib/cabinet/navigation';

export const metadata: Metadata = { title: 'Мои заявки' };

type Props = { searchParams: Promise<{ page?: string | string[] }> };

export default async function CabinetRequestsPage({ searchParams }: Props) {
  const { page } = await searchParams;
  return <RequestsList page={pageFromQuery(page)} />;
}
