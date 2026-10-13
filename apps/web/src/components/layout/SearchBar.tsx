/**
 * Поиск по каталогу.
 *
 * Отправка переводит на `/catalog?search=…` — запрос попадает в URL,
 * страницу можно сохранить и переслать. Форма настоящая (`<form>`),
 * чтобы работал Enter и поиск с мобильной клавиатуры. Отдельного
 * эндпоинта нет: выдачу ищет тот же `GET /public/products?search=`.
 */

'use client';

import { useRouter } from 'next/navigation';
import { useState, type Ref } from 'react';

import { catalogHref } from '@/lib/catalog-params';
import styles from './SearchBar.module.css';

export function SearchBar({
  defaultValue = '',
  placeholder = 'Поиск по артикулу или названию',
  className,
  inputRef,
}: {
  defaultValue?: string;
  placeholder?: string;
  className?: string;
  inputRef?: Ref<HTMLInputElement>;
}) {
  const router = useRouter();
  const [value, setValue] = useState(defaultValue);

  return (
    <form
      role="search"
      className={[styles.form, className ?? ''].filter(Boolean).join(' ')}
      onSubmit={(event) => {
        event.preventDefault();
        const query = value.trim();
        router.push(catalogHref(query ? { search: query } : {}));
      }}
    >
      <input
        ref={inputRef}
        className={styles.input}
        type="search"
        name="search"
        value={value}
        placeholder={placeholder}
        aria-label="Поиск по каталогу"
        enterKeyHint="search"
        onChange={(event) => setValue(event.target.value)}
      />
      <button type="submit" className={styles.submit}>
        Найти
      </button>
    </form>
  );
}
