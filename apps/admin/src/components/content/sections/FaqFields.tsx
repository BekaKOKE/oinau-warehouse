'use client';

import { useState } from 'react';

import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/States';
import { isLocEmpty } from '@/lib/content/fields';
import { emptyFaqItem, MAX_FAQ_ITEMS, type FaqForm } from '@/lib/content/faq';

import { ListEditor, LocField } from '../fields';
import { Panel } from '../FormContext';
import type { FieldsProps } from '../SectionEditor';
import { SeoPanel } from '../SeoPanel';
import styles from '../Content.module.css';

/** Предпросмотр русской версии в том порядке, в каком вопросы уйдут на сайт. */
function FaqPreview({ items }: { items: FaqForm['items'] }) {
  const filled = items.filter((item) => (item.question.ru ?? '').trim());
  if (filled.length === 0) {
    return <EmptyState compact title="Нечего показать" description="Добавьте вопрос с текстом." />;
  }
  return (
    <div className={styles.preview} aria-label="Предпросмотр FAQ">
      <p className={styles.muted}>Русская версия — так вопросы идут на странице FAQ.</p>
      <ol className={styles.previewList}>
        {filled.map((item, index) => (
          <li key={item.uid}>
            <details open={index === 0}>
              <summary>{item.question.ru?.trim()}</summary>
              <p>{item.answer.ru?.trim() || '—'}</p>
            </details>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function FaqFields({ form, update }: FieldsProps<FaqForm>) {
  const [preview, setPreview] = useState(false);

  return (
    <>
      <Panel
        title="Вопросы и ответы"
        description="Порядок на сайте — порядок в списке. Меняйте его кнопками ↑ ↓."
        paths={['items']}
        summary={`${form.items.length} из ${MAX_FAQ_ITEMS}`}
      >
        <div className={styles.panelToolbar}>
          <Button
            size="sm"
            variant={preview ? 'primary' : 'secondary'}
            icon={preview ? 'edit' : 'search'}
            aria-pressed={preview}
            onClick={() => setPreview((value) => !value)}
          >
            {preview ? 'Вернуться к редактированию' : 'Предпросмотр'}
          </Button>
        </div>
        {preview ? <FaqPreview items={form.items} /> : null}
        <div hidden={preview}>
          <ListEditor
            path="items"
            items={form.items}
            onChange={(items) => update((current) => ({ ...current, items }))}
            max={MAX_FAQ_ITEMS}
            create={emptyFaqItem}
            itemLabel={(index) => `Вопрос ${index + 1}`}
            itemSummary={(item) => item.question.ru ?? ''}
            isFilled={(item) => !isLocEmpty(item.question) || !isLocEmpty(item.answer)}
            addLabel="Добавить вопрос"
            emptyTitle="Вопросов пока нет"
            emptyDescription="Страница FAQ на сайте будет пустой."
          >
            {(item, index, patch) => (
              <>
                <LocField
                  label="Вопрос"
                  path={`items.${index}.question`}
                  kind="question"
                  required
                  value={item.question}
                  onChange={(question) => patch({ question })}
                />
                <LocField
                  label="Ответ"
                  path={`items.${index}.answer`}
                  kind="text"
                  required
                  rows={4}
                  value={item.answer}
                  onChange={(answer) => patch({ answer })}
                  hint="Простой текст, абзацы — переводом строки"
                />
              </>
            )}
          </ListEditor>
        </div>
      </Panel>

      <SeoPanel value={form.seo} onChange={(seo) => update((current) => ({ ...current, seo }))} />
    </>
  );
}
