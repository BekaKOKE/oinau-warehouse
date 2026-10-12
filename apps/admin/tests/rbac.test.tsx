/**
 * Доступ по ролям: навигация, прямые адреса и отсутствие лишних запросов.
 *
 * Матрица прав backend (app/modules/users/permissions.py) лежит в
 * `helpers.ts`; здесь проверяется, что интерфейс не показывает и не
 * запрашивает ничего сверх неё. Скрытая кнопка — не защита: каждый
 * запрос всё равно проверяет backend, поэтому проверяется и то,
 * и другое.
 */

import { render, screen, within } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import PanelLayout from '@/app/(panel)/layout';
import { AppProviders } from '@/components/AppProviders';
import { AttributesScreen } from '@/components/attributes/AttributesScreen';
import { AuditScreen } from '@/components/audit/AuditScreen';
import { CategoriesScreen } from '@/components/categories/CategoriesScreen';
import { ContentOverview } from '@/components/content/ContentScreens';
import { ImportExportScreen } from '@/components/imports/ImportExportScreen';
import { IntegrationScreen } from '@/components/integration/IntegrationScreen';
import { ProductCreateScreen } from '@/components/products/ProductCreateScreen';
import { ProductsList } from '@/components/products/ProductsList';
import { RequestsList } from '@/components/requests/RequestsList';
import { AuthGate } from '@/components/session/AuthGate';
import { StockScreen } from '@/components/stock/StockScreen';
import { UsersScreen } from '@/components/users/UsersScreen';
import type { UserRole } from '@/lib/api/types';
import { resetSessionForTests } from '@/lib/auth/session';

import { createFetchMock, signInAs } from './helpers';
import { navigationState } from './setup';

let net: ReturnType<typeof createFetchMock>;

function renderInPanel(ui: ReactNode) {
  return render(
    <AppProviders>
      <AuthGate>{ui}</AuthGate>
    </AppProviders>,
  );
}

beforeEach(() => {
  resetSessionForTests();
  net = createFetchMock();
  vi.stubGlobal('fetch', net.mock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/** Разделы, которые должны быть в боковом меню у роли. */
const NAV_BY_ROLE: Record<UserRole, string[]> = {
  SUPERADMIN: [
    'Dashboard',
    'Заявки',
    'Товары',
    'Категории',
    'Характеристики',
    'Цвета',
    'Склад',
    'Импорт / экспорт',
    'Контент',
    'Пользователи',
    'Аудит',
    'Интеграции',
  ],
  ADMIN: [
    'Dashboard',
    'Заявки',
    'Товары',
    'Категории',
    'Характеристики',
    'Цвета',
    'Склад',
    'Импорт / экспорт',
    'Контент',
    'Пользователи',
    'Аудит',
    'Интеграции',
  ],
  CONTENT_MANAGER: [
    'Dashboard',
    'Товары',
    'Категории',
    'Характеристики',
    'Цвета',
    'Склад',
    'Импорт / экспорт',
    'Контент',
  ],
  MANAGER: ['Dashboard', 'Заявки', 'Товары', 'Склад', 'Импорт / экспорт'],
  // У VIEWER есть request.read — заявки он видит, но только читает.
  VIEWER: ['Dashboard', 'Заявки', 'Товары', 'Склад', 'Импорт / экспорт'],
  // У кладовщика пока нет ни одного права — виден только Dashboard.
  WAREHOUSE: ['Dashboard'],
};

async function navLinks(role: UserRole) {
  signInAs(net, role);
  renderInPanel(
    <PanelLayout>
      <p>контент</p>
    </PanelLayout>,
  );
  const sidebar = await screen.findByRole('complementary', { name: 'Разделы' });
  // В боковой панели кроме списка разделов есть логотип и ссылка на сайт.
  return within(within(sidebar).getByRole('navigation'))
    .getAllByRole('link')
    .map((link) => link.textContent);
}

describe('навигация по ролям', () => {
  it.each(Object.keys(NAV_BY_ROLE) as UserRole[])('%s видит ровно свои разделы', async (role) => {
    expect(await navLinks(role)).toEqual(NAV_BY_ROLE[role]);
  });
});

/**
 * Прямой адрес раздела: роль без права видит «Нет доступа», и запрос,
 * который backend заведомо отклонит, не отправляется.
 */
describe('прямой адрес без права', () => {
  const CASES: {
    name: string;
    path: string;
    screen: ReactNode;
    forbiddenFor: UserRole[];
    apis: string[];
  }[] = [
    {
      name: 'Заявки',
      path: '/requests',
      screen: <RequestsList />,
      forbiddenFor: ['CONTENT_MANAGER'],
      apis: ['/api/v1/admin/requests'],
    },
    {
      name: 'Товары',
      path: '/products',
      screen: <ProductsList />,
      forbiddenFor: [],
      apis: ['/api/v1/admin/products'],
    },
    {
      name: 'Новый товар',
      path: '/products/new',
      screen: <ProductCreateScreen />,
      forbiddenFor: ['MANAGER', 'VIEWER'],
      apis: ['/api/v1/admin/categories/tree'],
    },
    {
      name: 'Категории',
      path: '/categories',
      screen: <CategoriesScreen />,
      forbiddenFor: [],
      apis: ['/api/v1/admin/categories/tree'],
    },
    {
      name: 'Характеристики',
      path: '/attributes',
      screen: <AttributesScreen />,
      forbiddenFor: [],
      apis: ['/api/v1/admin/attributes'],
    },
    {
      name: 'Склад',
      path: '/stock',
      screen: <StockScreen />,
      forbiddenFor: [],
      apis: ['/api/v1/admin/stock'],
    },
    {
      name: 'Контент',
      path: '/content',
      screen: <ContentOverview />,
      forbiddenFor: ['MANAGER', 'VIEWER'],
      apis: ['/api/v1/admin/content'],
    },
    {
      name: 'Импорт / экспорт',
      path: '/import-export',
      screen: <ImportExportScreen />,
      forbiddenFor: [],
      apis: ['/api/v1/admin/catalog/imports'],
    },
    {
      name: 'Пользователи',
      path: '/users',
      screen: <UsersScreen />,
      forbiddenFor: ['MANAGER', 'CONTENT_MANAGER', 'VIEWER'],
      apis: ['/api/v1/admin/users'],
    },
    {
      name: 'Аудит',
      path: '/audit',
      screen: <AuditScreen />,
      forbiddenFor: ['MANAGER', 'CONTENT_MANAGER', 'VIEWER'],
      apis: ['/api/v1/admin/audit'],
    },
    {
      name: 'Интеграции',
      path: '/integration',
      screen: <IntegrationScreen />,
      forbiddenFor: ['MANAGER', 'CONTENT_MANAGER', 'VIEWER'],
      apis: ['/api/v1/admin/integration/status'],
    },
  ];

  for (const testCase of CASES) {
    for (const role of testCase.forbiddenFor) {
      it(`${testCase.name}: ${role} видит «Нет доступа» и не шлёт запрос`, async () => {
        signInAs(net, role);
        navigationState.pathname = testCase.path;
        renderInPanel(testCase.screen);

        expect(await screen.findByText('Нет доступа')).toBeInTheDocument();
        for (const api of testCase.apis) {
          expect(net.calls('GET', api)).toHaveLength(0);
        }
      });
    }
  }
});
