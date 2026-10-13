import type { Metadata } from 'next';

import { CabinetFavorites } from '@/components/cabinet/CabinetFavorites';
import { pageFromQuery } from '@/lib/cabinet/navigation';

export const metadata: Metadata = { title: 'Избранное' };

type Props = { searchParams: Promise<{ page?: string | string[] }> };

export default async function CabinetFavoritesPage({ searchParams }: Props) {
  const { page } = await searchParams;
  return <CabinetFavorites page={pageFromQuery(page)} />;
}
