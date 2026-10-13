import type { Metadata } from 'next';

import { RequestDetailView } from '@/components/cabinet/RequestDetailView';

type Props = { params: Promise<{ number: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { number } = await params;
  return { title: `Заявка ${decodeURIComponent(number)}` };
}

export default async function CabinetRequestPage({ params }: Props) {
  const { number } = await params;
  return <RequestDetailView number={decodeURIComponent(number)} />;
}
