'use client';

/**
 * Категории: дерево слева, выбранная категория справа.
 *
 * Выбранная категория и режим создания живут в адресе (?id=, ?new=), так
 * что ссылку на раздел можно переслать, а «назад» возвращает к дереву.
 * На узком экране панели идут по очереди: дерево или карточка.
 */

import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { RequirePermission } from '@/components/session/AuthGate';
import { useSession } from '@/components/session/SessionProvider';
import { Button } from '@/components/ui/Button';
import { Checkbox, Input } from '@/components/ui/Field';
import { Card, PageHeader } from '@/components/ui/Layout';
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/States';
import { categoriesApi } from '@/lib/api/endpoints';
import { Permission } from '@/lib/auth/permissions';
import { expandableIds, filterTree, indexTree } from '@/lib/categories';
import { formatCount, plural } from '@/lib/format';
import { useQuery } from '@/lib/hooks/useQuery';

import { CategoryPanel } from './CategoryPanel';
import { CategoryTree } from './CategoryTree';
import styles from './Categories.module.css';

/**
 * Данные запрашиваются только внутри `RequirePermission`: роли без
 * права не нужен ни запрос, ни гарантированный 403.
 */
export function CategoriesScreen() {
  return (
    <RequirePermission all={[Permission.CATALOG_READ]}>
      <CategoriesPanel />
    </RequirePermission>
  );
}

function CategoriesPanel() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const { can } = useSession();
  const canWrite = can(Permission.CATALOG_WRITE);

  const selectedParam = params.get('id');
  const selectedId = selectedParam && /^\d+$/.test(selectedParam) ? Number(selectedParam) : null;
  const creatingParent = params.get('new');
  const creating = creatingParent !== null && canWrite;

  const [showDeleted, setShowDeleted] = useState(false);
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const tree = useQuery(
    (signal) => categoriesApi.tree({ signal, includeDeleted: showDeleted }),
    [showDeleted],
  );
  const nodes = useMemo(() => tree.data ?? [], [tree.data]);
  const index = useMemo(() => indexTree(nodes), [nodes]);
  const visible = useMemo(() => filterTree(nodes, search), [nodes, search]);

  // При поиске раскрываем всё найденное, иначе совпадение прячется в ветке.
  const effectiveExpanded = useMemo(
    () => (search.trim() ? new Set(expandableIds(visible)) : expanded),
    [search, visible, expanded],
  );

  // Выбранная категория должна быть видна: раскрываем её предков.
  useEffect(() => {
    if (!selectedId || !tree.data) return;
    setExpanded((current) => {
      const next = new Set(current);
      let parent = index.parentOf.get(selectedId);
      while (parent !== null && parent !== undefined) {
        next.add(parent);
        parent = index.parentOf.get(parent);
      }
      return next.size === current.size ? current : next;
    });
  }, [selectedId, tree.data, index]);

  const navigate = useCallback(
    (query: string) => router.replace(`${pathname}${query}`, { scroll: false }),
    [router, pathname],
  );

  const select = (id: number) => navigate(`?id=${id}`);
  const toggle = (id: number) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const total = index.byId.size;
  const deletedCount = [...index.byId.values()].filter((node) => node.deleted_at).length;
  const detailOpen = creating || selectedId !== null;

  return (
    <>
      <PageHeader
        title="Категории"
        description={
          tree.data
            ? `${formatCount(total - deletedCount)} ${plural(total - deletedCount, ['категория', 'категории', 'категорий'])}${
                deletedCount ? `, удалённых: ${formatCount(deletedCount)}` : ''
              }`
            : 'Дерево разделов каталога'
        }
        actions={
          canWrite ? (
            <Button variant="primary" icon="plus" onClick={() => navigate('?new=')}>
              Новая категория
            </Button>
          ) : null
        }
      />

      <div className={`${styles.layout} ${detailOpen ? styles.detailOpen : ''}`}>
        <Card flush className={styles.treeCard}>
          <div className={styles.treeToolbar}>
            <Input
              type="search"
              aria-label="Поиск категории"
              placeholder="Название или slug"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            <div className={styles.treeActions}>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setExpanded(new Set(expandableIds(nodes)))}
              >
                Развернуть всё
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setExpanded(new Set())}>
                Свернуть
              </Button>
              <Checkbox
                label="Удалённые"
                checked={showDeleted}
                onChange={(event) => setShowDeleted(event.target.checked)}
              />
            </div>
          </div>

          <div className={styles.treeBody} aria-busy={tree.isRefreshing || undefined}>
            {tree.status === 'error' && !tree.data ? (
              <ErrorState error={tree.error} onRetry={tree.reload} compact />
            ) : !tree.data ? (
              <div className={styles.treeSkeleton} aria-busy="true" data-testid="tree-skeleton">
                {Array.from({ length: 6 }, (_, item) => (
                  <Skeleton key={item} height={32} width={`${90 - item * 8}%`} />
                ))}
              </div>
            ) : nodes.length === 0 ? (
              <EmptyState
                icon="categories"
                title="Категорий пока нет"
                description={canWrite ? 'Создайте первый раздел каталога.' : undefined}
                compact
              />
            ) : visible.length === 0 ? (
              <EmptyState icon="search" title="Ничего не найдено" compact />
            ) : (
              <CategoryTree
                nodes={visible}
                expanded={effectiveExpanded}
                selectedId={selectedId}
                onToggle={toggle}
                onSelect={select}
              />
            )}
          </div>
        </Card>

        <div className={styles.detail}>
          {detailOpen ? (
            <CategoryPanel
              key={creating ? `new-${creatingParent}` : `edit-${selectedId}`}
              categoryId={creating ? null : selectedId}
              defaultParentId={
                creatingParent && /^\d+$/.test(creatingParent) ? Number(creatingParent) : null
              }
              tree={nodes}
              canWrite={canWrite}
              onClose={() => navigate('')}
              onSaved={(id) => {
                tree.reload();
                navigate(`?id=${id}`);
              }}
              onTreeChanged={tree.reload}
              onAddChild={(parentId) => navigate(`?new=${parentId}`)}
            />
          ) : (
            <Card>
              <EmptyState
                icon="categories"
                title="Выберите категорию"
                description="Карточка категории и её характеристики откроются здесь."
              />
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
