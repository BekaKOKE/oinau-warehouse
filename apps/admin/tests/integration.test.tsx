/**
 * Раздел «Интеграции»: состояние каналов и обменов.
 *
 * Главное, что здесь проверяется, — раздел не показывает реквизитов
 * и закрыт для ролей без права настроек.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AppProviders } from '@/components/AppProviders';
import { IntegrationScreen } from '@/components/integration/IntegrationScreen';
import { AuthGate } from '@/components/session/AuthGate';
import type { IntegrationStatus, UserRole } from '@/lib/api/types';
import { resetSessionForTests } from '@/lib/auth/session';

import { createFetchMock, errorResponse, signInAs } from './helpers';
import { navigationState } from './setup';

const STATUS_URL = '/api/v1/admin/integration/status';

let net: ReturnType<typeof createFetchMock>;

function renderInPanel(ui: ReactNode) {
  return render(
    <AppProviders>
      <AuthGate>{ui}</AuthGate>
    </AppProviders>,
  );
}

function makeStatus(overrides: Partial<IntegrationStatus> = {}): IntegrationStatus {
  return {
    channels: [
      { channel: 'telegram', enabled: true, reason: null, recipients: 2 },
      { channel: 'email', enabled: false, reason: 'not_configured', recipients: 0 },
    ],
    outbox: { pending: 3, sent: 128, skipped: 4, failed: 1 },
    one_c_enabled: false,
    api_keys_active: 1,
    last_syncs: [
      {
        entity: 'stock',
        status: 'success',
        received: 120,
        created: 0,
        updated: 118,
        skipped: 2,
        failed: 0,
        duration_ms: 340,
        created_at: '2026-09-18T06:00:00Z',
      },
    ],
    last_failure: {
      entity: 'price',
      status: 'partial',
      received: 40,
      created: 0,
      updated: 38,
      skipped: 0,
      failed: 2,
      duration_ms: 210,
      created_at: '2026-09-17T09:15:00Z',
    },
    ...overrides,
  };
}

async function openIntegration(role: UserRole = 'ADMIN', status: IntegrationStatus = makeStatus()) {
  signInAs(net, role);
  navigationState.pathname = '/integration';
  net.on('GET', STATUS_URL, status);
  renderInPanel(<IntegrationScreen />);
  await screen.findByRole('heading', { name: 'Интеграции', level: 1 });
}

beforeEach(() => {
  resetSessionForTests();
  net = createFetchMock();
  vi.stubGlobal('fetch', net.mock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('состояние каналов', () => {
  it('показывает включённый и выключенный канал с причиной', async () => {
    await openIntegration();

    expect(await screen.findByText('Telegram')).toBeInTheDocument();
    expect(screen.getByText('Включён')).toBeInTheDocument();
    expect(screen.getByText('2 получателя')).toBeInTheDocument();
    expect(screen.getByText('Электронная почта')).toBeInTheDocument();
    expect(screen.getByText('Реквизиты не заданы')).toBeInTheDocument();
  });

  it('общий выключатель объясняется отдельной причиной', async () => {
    await openIntegration(
      'ADMIN',
      makeStatus({
        channels: [
          { channel: 'telegram', enabled: false, reason: 'disabled_globally', recipients: 2 },
          { channel: 'email', enabled: false, reason: 'disabled_globally', recipients: 1 },
        ],
      }),
    );

    expect(await screen.findAllByText('Уведомления выключены настройкой')).toHaveLength(2);
  });

  it('счётчики очереди показываются', async () => {
    await openIntegration();

    expect(await screen.findByText('128')).toBeInTheDocument();
    expect(screen.getByText('Ожидают')).toBeInTheDocument();
    expect(screen.getByText('Не доставлено')).toBeInTheDocument();
  });
});

describe('обмен с 1С', () => {
  it('показывает выключенный обмен и число ключей', async () => {
    await openIntegration();

    expect(await screen.findByText('Обмен выключен')).toBeInTheDocument();
    expect(screen.getByText('1 действующий ключ')).toBeInTheDocument();
  });

  it('показывает последний обмен и последний сбой', async () => {
    await openIntegration();

    expect(await screen.findByText('Остатки')).toBeInTheDocument();
    expect(screen.getByText('Успешно')).toBeInTheDocument();
    expect(screen.getByText(/Последний сбой: Цены/)).toBeInTheDocument();
  });

  it('без обменов объясняет пустоту', async () => {
    await openIntegration('ADMIN', makeStatus({ last_syncs: [], last_failure: null }));

    expect(await screen.findByText('Обменов ещё не было')).toBeInTheDocument();
  });
});

describe('безопасность', () => {
  it('в разделе нет ни одного реквизита', async () => {
    const { container } = render(<div />);
    container.remove();
    await openIntegration();
    await screen.findByText('Telegram');

    const text = document.body.textContent ?? '';
    for (const secret of ['token', 'password', 'smtp', 'oik_', '@oinau']) {
      expect(text.toLowerCase()).not.toContain(secret);
    }
  });

  it.each(['MANAGER', 'CONTENT_MANAGER', 'VIEWER'] as const)(
    'роль %s видит «Нет доступа» и не запрашивает состояние',
    async (role) => {
      signInAs(net, role);
      navigationState.pathname = '/integration';
      renderInPanel(<IntegrationScreen />);

      expect(await screen.findByText('Нет доступа')).toBeInTheDocument();
      expect(net.calls('GET', STATUS_URL)).toHaveLength(0);
    },
  );

  it('ошибка загрузки предлагает повтор', async () => {
    signInAs(net, 'ADMIN');
    navigationState.pathname = '/integration';
    net.on('GET', STATUS_URL, errorResponse(500, 'internal_error', 'Внутренняя ошибка сервера'));
    renderInPanel(<IntegrationScreen />);

    expect(await screen.findByText('Не удалось загрузить данные')).toBeInTheDocument();

    const user = userEvent.setup();
    net.on('GET', STATUS_URL, makeStatus());
    await user.click(screen.getByRole('button', { name: 'Повторить' }));

    expect(await screen.findByText('Telegram')).toBeInTheDocument();
  });

  it('кнопка «Обновить» перечитывает состояние', async () => {
    await openIntegration();
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: 'Обновить' }));

    await waitFor(() => expect(net.calls('GET', STATUS_URL).length).toBeGreaterThan(1));
  });

  it('раздел только читает: ничего, кроме GET, не отправляется', async () => {
    await openIntegration();

    const methods = net.mock.mock.calls
      .filter(([url]) => new URL(String(url)).pathname === STATUS_URL)
      .map(([, init]) => (init as RequestInit | undefined)?.method ?? 'GET');
    expect(new Set(methods)).toEqual(new Set(['GET']));
  });
});

describe('ссылка в аудит', () => {
  it('ведёт к изменениям, сделанным обменом', async () => {
    await openIntegration();

    const link = await screen.findByRole('link', { name: /Изменения из 1С/ });
    expect(link).toHaveAttribute('href', '/audit?entity=product&actor=1c');
  });
});

describe('навигация', () => {
  it('раздел доступен только с правом настроек', async () => {
    const { visibleNav } = await import('@/lib/navigation');

    const admin = visibleNav(new Set(['settings.write', 'catalog.read']))
      .flatMap((group) => group.items)
      .map((item) => item.href);
    const manager = visibleNav(new Set(['request.read', 'catalog.read']))
      .flatMap((group) => group.items)
      .map((item) => item.href);

    expect(admin).toContain('/integration');
    expect(manager).not.toContain('/integration');
  });
});

/** Значения `reason` берутся из backend — проверяем, что все переведены. */
describe('подписи причин', () => {
  it.each(['not_configured', 'disabled_globally', 'no_recipients'])(
    'причина %s переведена',
    async (reason) => {
      await openIntegration(
        'ADMIN',
        makeStatus({
          channels: [{ channel: 'telegram', enabled: false, reason, recipients: 0 }],
        }),
      );

      const card = await screen.findByText('Telegram');
      const container = card.closest('div')?.parentElement;
      expect(within(container as HTMLElement).queryByText(reason)).not.toBeInTheDocument();
    },
  );
});
