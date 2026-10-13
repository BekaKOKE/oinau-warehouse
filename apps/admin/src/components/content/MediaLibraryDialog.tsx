'use client';

/**
 * Выбор готового изображения из медиатеки (GET /media, только READY):
 * один и тот же файл может использоваться и в товаре, и в разделе CMS.
 */

import { useEffect, useState } from 'react';

import { Dialog } from '@/components/ui/Dialog';
import { Input } from '@/components/ui/Field';
import { Pagination } from '@/components/ui/Pagination';
import { EmptyState, ErrorState, Skeleton } from '@/components/ui/States';
import { mediaApi } from '@/lib/api/endpoints';
import type { MediaRead } from '@/lib/api/types';
import { useQuery } from '@/lib/hooks/useQuery';

import styles from './Content.module.css';

export const LIBRARY_PAGE_SIZE = 24;
const SEARCH_DELAY_MS = 300;

function thumb(media: MediaRead): string | null {
  return media.variants?.thumb ?? media.url ?? null;
}

export function MediaLibraryDialog({
  open,
  onClose,
  onSelect,
}: {
  open: boolean;
  onClose: () => void;
  onSelect: (media: MediaRead) => void;
}) {
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setQuery(search.trim());
      setPage(1);
    }, SEARCH_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [search]);

  const list = useQuery(
    (signal) =>
      mediaApi.list(
        { status: 'READY', search: query || undefined, page, page_size: LIBRARY_PAGE_SIZE },
        { signal },
      ),
    [query, page],
    { enabled: open },
  );

  const items = list.data?.items ?? [];

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Медиатека"
      description="Готовые изображения. Выбранный файл станет ссылкой в разделе после сохранения."
      size="lg"
    >
      <div className={styles.library}>
        <Input
          type="search"
          value={search}
          placeholder="Имя файла"
          aria-label="Поиск по имени файла"
          onChange={(event) => setSearch(event.target.value)}
        />
        {list.status === 'error' && !list.data ? (
          <ErrorState error={list.error} onRetry={list.reload} compact />
        ) : !list.data ? (
          <div className={styles.libraryGrid} role="status" aria-label="Загрузка медиатеки">
            {Array.from({ length: 8 }, (_, index) => (
              <Skeleton key={index} height={120} />
            ))}
          </div>
        ) : items.length === 0 ? (
          <EmptyState
            compact
            icon="image"
            title={query ? 'Ничего не найдено' : 'В медиатеке нет готовых изображений'}
            description={query ? 'Измените запрос.' : 'Загрузите файл кнопкой «Загрузить».'}
          />
        ) : (
          <>
            <ul className={styles.libraryGrid} aria-label="Изображения медиатеки">
              {items.map((media) => {
                const src = thumb(media);
                const name = media.original_filename ?? 'Без имени';
                return (
                  <li key={media.uuid}>
                    <button
                      type="button"
                      className={styles.libraryItem}
                      onClick={() => onSelect(media)}
                      aria-label={`Выбрать ${name}`}
                    >
                      {src ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={src} alt="" loading="lazy" />
                      ) : (
                        <span className={styles.mediaEmpty}>Нет превью</span>
                      )}
                      <span className={styles.libraryName}>{name}</span>
                      {media.width && media.height ? (
                        <span className={`num ${styles.muted}`}>
                          {media.width}×{media.height}
                        </span>
                      ) : null}
                    </button>
                  </li>
                );
              })}
            </ul>
            <Pagination
              page={page}
              pages={list.data.pages}
              total={list.data.total}
              pageSize={LIBRARY_PAGE_SIZE}
              onPageChange={setPage}
              disabled={list.isRefreshing}
            />
          </>
        )}
      </div>
    </Dialog>
  );
}
