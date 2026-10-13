'use client';

/**
 * Загрузка данных для экрана.
 *
 * Отдельная библиотека кеширования админке не нужна: экраны читают
 * свежие данные при открытии, а после изменения перечитывают их явно.
 * Хук отвечает за три вещи, которые легко забыть в каждом компоненте:
 * отмену устаревшего запроса при смене параметров, отсутствие гонок
 * (ответ старого запроса не перезапишет новый) и единый вид состояния.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { isAbortError } from '@/lib/api/client';

export type QueryState<T> =
  | { status: 'loading'; data: T | undefined; error: null }
  | { status: 'success'; data: T; error: null }
  | { status: 'error'; data: T | undefined; error: unknown };

export type QueryResult<T> = QueryState<T> & {
  /** Перечитать данные. Прежние данные остаются на экране до ответа. */
  reload: () => void;
  /** Подменить данные ответом мутации без повторного запроса. */
  setData: (data: T) => void;
  isRefreshing: boolean;
};

export function useQuery<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[],
  { enabled = true }: { enabled?: boolean } = {},
): QueryResult<T> {
  const [state, setState] = useState<QueryState<T>>({
    status: 'loading',
    data: undefined,
    error: null,
  });
  const [isRefreshing, setRefreshing] = useState(false);
  const [version, setVersion] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    setRefreshing(true);
    setState((previous) =>
      previous.status === 'success'
        ? previous
        : { status: 'loading', data: previous.data, error: null },
    );
    fetcherRef
      .current(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setState({ status: 'success', data, error: null });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || isAbortError(error)) return;
        setState((previous) => ({ status: 'error', data: previous.data, error }));
      })
      .finally(() => {
        if (!controller.signal.aborted) setRefreshing(false);
      });
    return () => controller.abort();
    // Зависимости задаёт вызывающий: fetcher пересоздаётся на каждый рендер.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, version, enabled]);

  const reload = useCallback(() => setVersion((value) => value + 1), []);
  const setData = useCallback((data: T) => setState({ status: 'success', data, error: null }), []);

  return { ...state, reload, setData, isRefreshing };
}
