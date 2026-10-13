'use client';

/**
 * Дерево категорий: раскрытие и сворачивание, выбор, признаки
 * (скрыта, удалена), число товаров и подкатегорий.
 *
 * Перетаскивания нет намеренно: перенос ветки делается сменой родителя
 * в форме — backend пересчитывает путь всей ветки и проверяет циклы.
 */

import type { KeyboardEvent } from 'react';

import { Badge } from '@/components/ui/Badge';
import { Icon } from '@/components/ui/Icon';
import type { CategoryTreeNode } from '@/lib/api/types';
import { liveChildren } from '@/lib/categories';
import { formatCount } from '@/lib/format';

import styles from './Categories.module.css';

type Props = {
  nodes: readonly CategoryTreeNode[];
  expanded: ReadonlySet<number>;
  selectedId: number | null;
  onToggle: (id: number) => void;
  onSelect: (id: number) => void;
};

export function CategoryTree({ nodes, expanded, selectedId, onToggle, onSelect }: Props) {
  const renderNode = (node: CategoryTreeNode, level: number) => {
    const children = node.children ?? [];
    const hasChildren = children.length > 0;
    const isExpanded = expanded.has(node.id);
    const selected = node.id === selectedId;
    const deleted = Boolean(node.deleted_at);
    const live = liveChildren(node).length;

    const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        onSelect(node.id);
      } else if (event.key === 'ArrowRight' && hasChildren && !isExpanded) {
        onToggle(node.id);
      } else if (event.key === 'ArrowLeft' && hasChildren && isExpanded) {
        onToggle(node.id);
      }
    };

    return (
      <li
        key={node.id}
        role="treeitem"
        aria-level={level}
        aria-expanded={hasChildren ? isExpanded : undefined}
        aria-selected={selected}
        className={styles.treeItem}
      >
        <div
          className={`${styles.row} ${selected ? styles.rowSelected : ''} ${deleted ? styles.rowDeleted : ''}`}
          style={{ paddingLeft: 8 + (level - 1) * 18 }}
          tabIndex={0}
          onClick={() => onSelect(node.id)}
          onKeyDown={onKeyDown}
          data-testid={`category-row-${node.id}`}
        >
          {hasChildren ? (
            <button
              type="button"
              className={styles.toggle}
              aria-label={`${isExpanded ? 'Свернуть' : 'Развернуть'} «${node.name}»`}
              onClick={(event) => {
                event.stopPropagation();
                onToggle(node.id);
              }}
            >
              <Icon name={isExpanded ? 'chevronDown' : 'chevronRight'} size={14} />
            </button>
          ) : (
            <span className={styles.toggleSpacer} aria-hidden="true" />
          )}
          <span className={styles.rowMain}>
            <span className={styles.rowName}>{node.name}</span>
            <span className={`mono ${styles.rowSlug}`}>{node.slug}</span>
          </span>
          <span className={styles.rowMeta}>
            {deleted ? (
              <Badge tone="danger">Удалена</Badge>
            ) : !node.is_active ? (
              <Badge tone="warning">Скрыта</Badge>
            ) : null}
            {live > 0 ? (
              <span className={styles.metaCount} title="Подкатегорий">
                <Icon name="categories" size={12} /> {formatCount(live)}
              </span>
            ) : null}
            <span className={styles.metaCount} title="Товаров">
              <Icon name="products" size={12} /> {formatCount(node.products_count)}
            </span>
          </span>
        </div>
        {hasChildren && isExpanded ? (
          <ul role="group" className={styles.treeGroup}>
            {children.map((child) => renderNode(child, level + 1))}
          </ul>
        ) : null}
      </li>
    );
  };

  return (
    <ul role="tree" aria-label="Дерево категорий" className={styles.tree}>
      {nodes.map((node) => renderNode(node, 1))}
    </ul>
  );
}
