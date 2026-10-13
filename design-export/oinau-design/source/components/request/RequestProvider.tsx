/**
 * Состав заявки.
 *
 * Заявка — основной сценарий сайта, поэтому её состав переживает
 * перезагрузку страницы: посетитель собирает спецификацию не за один
 * заход. Хранится он в localStorage конкретного браузера и на сервер
 * до отправки формы не уходит.
 *
 * В позиции лежит снимок для показа (название, единица, цена), но
 * отправляются только `sku` и количество: цену и наименование сервер
 * берёт из каталога сам и клиентским данным не верит.
 */

'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import type { NewRequestLine, RequestLine } from '@/lib/request-line';

const STORAGE_KEY = 'oinau.request.v1';

type RequestState = {
  lines: RequestLine[];
  /** false, пока не прочитан localStorage: счётчик не должен мигать. */
  ready: boolean;
  count: number;
  add: (line: NewRequestLine & { quantity?: number }) => void;
  setQuantity: (sku: string, quantity: number) => void;
  remove: (sku: string) => void;
  clear: () => void;
  has: (sku: string) => boolean;
};

const RequestContext = createContext<RequestState | null>(null);

function parseStored(raw: string | null): RequestLine[] {
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isLine);
  } catch {
    // Повреждённое или устаревшее хранилище не должно ронять сайт.
    return [];
  }
}

function isLine(value: unknown): value is RequestLine {
  if (typeof value !== 'object' || value === null) return false;
  const line = value as Record<string, unknown>;
  return (
    typeof line.sku === 'string' &&
    typeof line.slug === 'string' &&
    typeof line.name === 'string' &&
    typeof line.unit === 'string' &&
    typeof line.quantity === 'number' &&
    Number.isFinite(line.quantity) &&
    line.quantity > 0
  );
}

export function RequestProvider({ children }: { children: ReactNode }) {
  const [lines, setLines] = useState<RequestLine[]>([]);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setLines(parseStored(window.localStorage.getItem(STORAGE_KEY)));
    setReady(true);
  }, []);

  useEffect(() => {
    if (!ready) return;
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(lines));
    } catch {
      // Приватный режим и переполненное хранилище: заявка продолжает
      // работать в памяти вкладки.
    }
  }, [lines, ready]);

  const add = useCallback<RequestState['add']>((line) => {
    const quantity = Math.max(line.quantity ?? line.minOrderQty ?? 1, line.minOrderQty || 1);
    setLines((current) => {
      const existing = current.find((item) => item.sku === line.sku);
      if (existing) {
        // Один товар — одна позиция: backend отвергает дубли артикулов.
        return current.map((item) =>
          item.sku === line.sku ? { ...item, ...line, quantity: item.quantity + quantity } : item,
        );
      }
      return [...current, { ...line, quantity }];
    });
  }, []);

  const setQuantity = useCallback<RequestState['setQuantity']>((sku, quantity) => {
    setLines((current) =>
      current.map((item) =>
        item.sku === sku ? { ...item, quantity: Math.max(quantity, item.minOrderQty || 1) } : item,
      ),
    );
  }, []);

  const remove = useCallback<RequestState['remove']>((sku) => {
    setLines((current) => current.filter((item) => item.sku !== sku));
  }, []);

  const clear = useCallback(() => setLines([]), []);

  const value = useMemo<RequestState>(
    () => ({
      lines,
      ready,
      count: lines.length,
      add,
      setQuantity,
      remove,
      clear,
      has: (sku: string) => lines.some((item) => item.sku === sku),
    }),
    [lines, ready, add, setQuantity, remove, clear],
  );

  return <RequestContext.Provider value={value}>{children}</RequestContext.Provider>;
}

export function useRequest(): RequestState {
  const context = useContext(RequestContext);
  if (!context) {
    throw new Error('useRequest используется вне RequestProvider');
  }
  return context;
}

export { STORAGE_KEY as REQUEST_STORAGE_KEY };
