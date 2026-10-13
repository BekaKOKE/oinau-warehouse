import type { ReactNode } from 'react';

import { Button } from '@/components/ui/Button';

import styles from '../ProductEditor.module.css';

/** Панель сохранения раздела: «Отменить» и «Сохранить» появляются при изменениях. */
export function SectionActions({
  dirty,
  saving,
  onReset,
  saveLabel = 'Сохранить',
  note,
}: {
  dirty: boolean;
  saving: boolean;
  onReset: () => void;
  saveLabel?: string;
  note?: ReactNode;
}) {
  return (
    <div className={styles.sectionActions}>
      <span className={styles.muted}>{dirty ? 'Есть несохранённые изменения' : note}</span>
      <div className={styles.sectionButtons}>
        <Button variant="ghost" disabled={!dirty || saving} onClick={onReset}>
          Отменить
        </Button>
        <Button type="submit" variant="primary" loading={saving} disabled={!dirty}>
          {saveLabel}
        </Button>
      </div>
    </div>
  );
}
