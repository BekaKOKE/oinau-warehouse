/**
 * Полоса «Знаете артикулы?» — вход в быстрый заказ по списку.
 *
 * Поле здесь — только черновик: «Оформить» открывает окно быстрого
 * заказа на вкладке «По артикулам» с уже вставленным текстом, там же
 * контакты и отправка. Разбирает список сервер.
 *
 * Пример в подсказке собирается из настоящих артикулов каталога, а не
 * выдумывается.
 */

'use client';

import { useState } from 'react';

import { useQuickOrder } from '@/components/quick-order/QuickOrderContext';
import styles from './Sections.module.css';

export function SkuQuickBar({ examples }: { examples: string[] }) {
  const { open } = useQuickOrder();
  const [value, setValue] = useState('');
  const placeholder =
    examples.length > 0
      ? `${examples
          .slice(0, 2)
          .map((sku, index) => `${sku} × ${index === 0 ? 20 : 4}`)
          .join(', ')} …`
      : 'Артикул × количество, через запятую или с новой строки';

  return (
    <section className="container" aria-labelledby="sku-bar-title">
      <form
        className={styles.skuBar}
        onSubmit={(event) => {
          event.preventDefault();
          open({ mode: 'SKU_LIST', skuList: value.trim() });
        }}
      >
        <h2 className={styles.skuTitle} id="sku-bar-title">
          Знаете артикулы? Вставьте список — соберём заказ сами
        </h2>
        <input
          className={styles.skuInput}
          type="text"
          name="sku_list"
          value={value}
          placeholder={placeholder}
          aria-label="Артикулы и количество"
          autoComplete="off"
          spellCheck={false}
          onChange={(event) => setValue(event.target.value)}
        />
        <button type="submit" className={styles.skuSubmit}>
          Оформить
        </button>
      </form>
    </section>
  );
}
