import type { Metadata } from 'next';

import { NotificationsList } from '@/components/cabinet/NotificationsList';
import { pageFromQuery } from '@/lib/cabinet/navigation';

export const metadata: Metadata = { title: 'Уведомления' };

type Props = { searchParams: Promise<{ page?: string | string[]; unread?: string }> };

export default async function CabinetNotificationsPage({ searchParams }: Props) {
  const { page, unread } = await searchParams;
  return <NotificationsList page={pageFromQuery(page)} unreadOnly={unread === '1'} />;
}
