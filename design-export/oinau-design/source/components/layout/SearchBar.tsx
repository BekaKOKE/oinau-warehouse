/**
 * Поиск по каталогу.
 *
 * Отправка переводит на `/catalog?search=…` — запрос попадает в URL,
 * страницу можно сохранить и переслать. Форма настоящая (`<form>`),
 * чтобы работал Enter и поиск с мобильной клавиатуры.
 */

'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { catalogHref } from '@/lib/catalog-params';
import styles from './SearchBar.module.css';

export function SearchBar({
  defaultValue = '',
  tone = 'dark',
  placeholder = 'Артикул, название или диаметр — напр. RP-016',
  className,
}: {
  defaultValue?: string;
  tone?: 'dark' | 'light';
  placeholder?: string;
  className?: string;
}) {
  const router = useRouter();
  const [value, setValue] = useState(defaultValue);

  return (
    <form
      role="search"
      className={[styles.form, tone === 'light' ? styles.light : '', className ?? '']
        .filter(Boolean)
        .join(' ')}
      onSubmit={(event) => {
        event.preventDefault();
        const query = value.trim();
        router.push(catalogHref(query ? { search: query } : {}));
      }}
    >
      <svg className={styles.icon} viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.8" />
        <path d="M11 11l4 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
      <input
        className={styles.input}
        type="search"
        name="search"
        value={value}
        placeholder={placeholder}
        aria-label="Поиск по каталогу"
        onChange={(event) => setValue(event.target.value)}
      />
      <button type="submit" className={styles.submit}>
        Найти
      </button>
    </form>
  );
}
