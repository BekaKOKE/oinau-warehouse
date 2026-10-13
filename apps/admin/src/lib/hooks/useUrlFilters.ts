'use client';

/**
 * Фильтры списка, живущие в адресной строке.
 *
 * Ссылку на выборку можно переслать, «назад» возвращает к ней, а переход
 * по ссылке снаружи (например, с дашборда) применяется без перезагрузки.
 * Поиск применяется после паузы ввода — без запроса на каждую букву.
 */

import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';

type Filters = { search: string; page: number };

type Options<T extends Filters> = {
  parse: (params: URLSearchParams) => T;
  serialize: (filters: T) => string;
  searchDelayMs?: number;
};

export function useUrlFilters<T extends Filters>({
  parse,
  serialize,
  searchDelayMs = 350,
}: Options<T>) {
  const router = useRouter();
  const pathname = usePathname();
  const paramsString = useSearchParams().toString();

  const [filters, setFilters] = useState<T>(() => parse(new URLSearchParams(paramsString)));
  const [searchInput, setSearchInput] = useState(filters.search);
  const lastWritten = useRef(serialize(filters));
  const current = useRef(filters);
  current.current = filters;

  useEffect(() => {
    const fromUrl = parse(new URLSearchParams(paramsString));
    const serialized = serialize(fromUrl);
    if (serialized === lastWritten.current) return;
    lastWritten.current = serialized;
    setFilters(fromUrl);
    setSearchInput(fromUrl.search);
    // parse/serialize — чистые функции модуля, пересоздание не нужно отслеживать.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramsString]);

  /** Любая смена фильтра, кроме страницы, возвращает на первую страницу. */
  const apply = (patch: Partial<T>) => {
    const next = { ...current.current, page: 1, ...patch } as T;
    const search = serialize(next);
    current.current = next;
    lastWritten.current = search;
    setFilters(next);
    router.replace(`${pathname}${search}`, { scroll: false });
  };

  useEffect(() => {
    if (searchInput.trim() === filters.search.trim()) return;
    const timer = window.setTimeout(
      () => apply({ search: searchInput } as Partial<T>),
      searchDelayMs,
    );
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput, filters.search]);

  return { filters, apply, searchInput, setSearchInput };
}
