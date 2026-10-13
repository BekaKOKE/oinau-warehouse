'use client';

/**
 * Раздел «Пользователи»: сотрудники, роли и доступ.
 *
 * Право одно — `user.manage` (ADMIN и SUPERADMIN), как в backend.
 * Состав ролей приходит из GET /admin/users/roles: своей копии матрицы
 * RBAC интерфейс не держит, иначе она разошлась бы с кодом сервера.
 */

import { useMemo, useState } from 'react';

import { RequirePermission } from '@/components/session/AuthGate';
import { useSession } from '@/components/session/SessionProvider';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { Field, Input, Select } from '@/components/ui/Field';
import { Card, PageHeader } from '@/components/ui/Layout';
import { Pagination } from '@/components/ui/Pagination';
import { EmptyState, Skeleton } from '@/components/ui/States';
import { usersApi } from '@/lib/api/endpoints';
import type { AdminUser, UserRole } from '@/lib/api/types';
import { Permission, PERMISSION_LABELS, ROLE_LABELS } from '@/lib/auth/permissions';
import type { PermissionCode } from '@/lib/auth/permissions';
import { formatCount, formatDateTime, plural } from '@/lib/format';
import { useQuery } from '@/lib/hooks/useQuery';
import { useUrlFilters } from '@/lib/hooks/useUrlFilters';
import {
  DEFAULT_USER_FILTERS,
  parseUserFilters,
  ROLE_HINTS,
  ROLE_OPTIONS,
  serializeUserFilters,
  userListQuery,
} from '@/lib/users';

import { UserDrawer } from './UserDrawer';
import styles from './Users.module.css';

const PAGE_SIZE = 24;

const STATUS_OPTIONS = [
  { value: 'active', label: 'Активные' },
  { value: 'disabled', label: 'Отключённые' },
];

function StatusBadge({ user }: { user: AdminUser }) {
  return user.is_active ? (
    <Badge tone="success" dot>
      Активен
    </Badge>
  ) : (
    <Badge tone="neutral" dot>
      Отключён
    </Badge>
  );
}

function RolesCard({
  roles,
  loading,
}: {
  roles: readonly { role: UserRole; permissions: string[] }[];
  loading: boolean;
}) {
  return (
    <Card
      title="Роли и права"
      description="Состав прав задан в backend: изменить его из интерфейса нельзя."
    >
      {loading && roles.length === 0 ? (
        <Skeleton height={64} />
      ) : (
        <div className={styles.roles}>
          {roles.map((item) => (
            <div key={item.role} className={styles.roleCard}>
              <span className={styles.roleName}>{ROLE_LABELS[item.role]}</span>
              <span className={styles.muted}>{ROLE_HINTS[item.role]}</span>
              <ul className={styles.permissions}>
                {item.permissions.map((permission) => (
                  <li key={permission}>
                    <Badge tone="neutral">
                      {PERMISSION_LABELS[permission as PermissionCode] ?? permission}
                    </Badge>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

/**
 * Данные раздела запрашиваются только внутри `RequirePermission`:
 * сотруднику без права не нужен ни запрос, ни гарантированный 403.
 */
export function UsersScreen() {
  return (
    <RequirePermission all={[Permission.USER_MANAGE]}>
      <UsersPanel />
    </RequirePermission>
  );
}

function UsersPanel() {
  const { user: me } = useSession();
  const { filters, apply, searchInput, setSearchInput } = useUrlFilters({
    parse: parseUserFilters,
    serialize: serializeUserFilters,
  });
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [drawer, setDrawer] = useState<'closed' | 'create' | 'edit'>('closed');

  const query = useMemo(() => userListQuery(filters, PAGE_SIZE), [filters]);
  const list = useQuery((signal) => usersApi.list(query, { signal }), [JSON.stringify(query)]);
  const roles = useQuery((signal) => usersApi.roles({ signal }), []);

  const data = list.data;
  const active = Boolean(filters.search.trim() || filters.role || filters.status);

  const openCreate = () => {
    setEditing(null);
    setDrawer('create');
  };
  const openEdit = (user: AdminUser) => {
    setEditing(user);
    setDrawer('edit');
  };

  const columns: Column<AdminUser>[] = [
    {
      key: 'name',
      header: 'Сотрудник',
      cell: (user) => (
        <div className={styles.stack}>
          <button type="button" className={styles.nameButton} onClick={() => openEdit(user)}>
            {user.full_name}
          </button>
          <span className={`${styles.muted} ${styles.email}`}>{user.email}</span>
          {me?.uuid === user.uuid ? (
            <span className={styles.you}>
              <Badge tone="info">Это вы</Badge>
            </span>
          ) : null}
        </div>
      ),
    },
    {
      key: 'role',
      header: 'Роль',
      cell: (user) => (
        <div className={styles.stack}>
          <span className={styles.strong}>{ROLE_LABELS[user.role]}</span>
          <span className={styles.muted}>{ROLE_HINTS[user.role]}</span>
        </div>
      ),
    },
    { key: 'status', header: 'Доступ', cell: (user) => <StatusBadge user={user} /> },
    {
      key: 'phone',
      header: 'Телефон',
      hideOnMobile: true,
      cell: (user) =>
        user.phone ? <span>{user.phone}</span> : <span className={styles.muted}>—</span>,
    },
    {
      key: 'activity',
      header: 'Последний вход',
      hideOnMobile: true,
      cell: (user) => (
        <div className={styles.stack}>
          <span>{user.last_login_at ? formatDateTime(user.last_login_at) : 'не входил'}</span>
          <span className={styles.muted}>заведён {formatDateTime(user.created_at)}</span>
        </div>
      ),
    },
    {
      key: 'actions',
      header: '',
      align: 'right',
      cell: (user) => (
        <Button size="sm" variant="ghost" icon="edit" onClick={() => openEdit(user)}>
          Изменить
        </Button>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Пользователи"
        description="Сотрудники с доступом в админку, их роли и состояние учётных записей."
        actions={
          <Button variant="primary" icon="plus" onClick={openCreate}>
            Новый сотрудник
          </Button>
        }
      />

      <Card flush>
        <form className={styles.filters} role="search" onSubmit={(e) => e.preventDefault()}>
          <Field label="Поиск" className={styles.search}>
            <Input
              type="search"
              placeholder="Имя или email"
              maxLength={255}
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
            />
          </Field>
          <Field label="Роль">
            <Select
              options={ROLE_OPTIONS}
              placeholder="Все роли"
              value={filters.role}
              onChange={(event) => apply({ role: event.target.value as UserRole | '' })}
            />
          </Field>
          <Field label="Доступ">
            <Select
              options={STATUS_OPTIONS}
              placeholder="Любой"
              value={filters.status}
              onChange={(event) =>
                apply({ status: event.target.value as 'active' | 'disabled' | '' })
              }
            />
          </Field>
        </form>
        <div className={styles.filtersFooter}>
          <span>
            {data
              ? `${formatCount(data.total)} ${plural(data.total, ['сотрудник', 'сотрудника', 'сотрудников'])}`
              : 'Загрузка…'}
          </span>
          {active ? (
            <Button
              size="sm"
              variant="ghost"
              icon="close"
              onClick={() => {
                setSearchInput('');
                apply(DEFAULT_USER_FILTERS);
              }}
            >
              Сбросить фильтры
            </Button>
          ) : null}
        </div>
        <DataTable
          caption="Сотрудники"
          columns={columns}
          rows={data?.items}
          rowKey={(user) => user.uuid}
          loading={list.status === 'loading'}
          refreshing={list.isRefreshing}
          error={list.status === 'error' ? list.error : undefined}
          onRetry={list.reload}
          onRowClick={openEdit}
          empty={
            active ? (
              <EmptyState
                icon="search"
                title="Никого не найдено"
                description="Измените условия поиска или сбросьте фильтры."
                compact
              />
            ) : (
              <EmptyState
                icon="users"
                title="Сотрудников пока нет"
                description="Заведите первого сотрудника кнопкой «Новый сотрудник»."
                compact
              />
            )
          }
          renderMobile={(user) => (
            <div className={styles.mobileCard}>
              <div className={styles.mobileTop}>
                <div className={styles.stack}>
                  <span className={styles.strong}>{user.full_name}</span>
                  <span className={`${styles.muted} ${styles.email}`}>{user.email}</span>
                </div>
                <StatusBadge user={user} />
              </div>
              <div className={styles.inline}>
                <Badge tone="info">{ROLE_LABELS[user.role]}</Badge>
                {me?.uuid === user.uuid ? <Badge tone="neutral">Это вы</Badge> : null}
              </div>
              <span className={styles.muted}>
                Последний вход:{' '}
                {user.last_login_at ? formatDateTime(user.last_login_at) : 'не входил'}
              </span>
              <Button size="sm" icon="edit" onClick={() => openEdit(user)}>
                Изменить
              </Button>
            </div>
          )}
        />
        {data ? (
          <Pagination
            page={data.page}
            pages={data.pages}
            total={data.total}
            pageSize={PAGE_SIZE}
            disabled={list.isRefreshing}
            onPageChange={(page) => apply({ page })}
          />
        ) : null}
      </Card>

      <RolesCard roles={roles.data ?? []} loading={roles.status === 'loading'} />

      <UserDrawer
        open={drawer !== 'closed'}
        user={drawer === 'edit' ? editing : null}
        roles={roles.data ?? []}
        onClose={() => setDrawer('closed')}
        onSaved={() => {
          setDrawer('closed');
          list.reload();
        }}
      />
    </>
  );
}
