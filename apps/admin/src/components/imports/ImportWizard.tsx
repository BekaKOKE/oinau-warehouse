'use client';

/**
 * Импорт каталога: файл → предпросмотр → применение.
 *
 * Разбор, проверку и применение делает backend. Экран отправляет книгу
 * и показывает его отчёт; ни одной проверки данных здесь не
 * придумывается. На подтверждение уходит ТОТ ЖЕ файл — сервер его не
 * хранит и сверяет SHA-256, поэтому выбранный File держится в состоянии
 * до конца сценария.
 *
 * Предпросмотр каталог не меняет и доступен всем, кто читает каталог;
 * применение требует catalog.write — как и в backend.
 */

import { useRef, useState, type DragEvent } from 'react';

import { useSession } from '@/components/session/SessionProvider';
import { Button, ButtonLink } from '@/components/ui/Button';
import { useConfirm } from '@/components/ui/Dialog';
import { Card } from '@/components/ui/Layout';
import { useToast } from '@/components/ui/Toast';
import { importsApi } from '@/lib/api/endpoints';
import type { ImportCommitResult, ImportPreview } from '@/lib/api/types';
import { Permission } from '@/lib/auth/permissions';
import { describeError } from '@/lib/errors';
import { formatBytes, formatCount, plural } from '@/lib/format';
import {
  changePartLabel,
  checkXlsxFile,
  hasChanges,
  issuesFromError,
  MAX_FILE_SIZE_MB,
  summaryRows,
  totalChanges,
  uploadErrorText,
  XLSX_ACCEPT,
} from '@/lib/imports';

import { IssueList } from './IssueList';
import styles from './ImportExport.module.css';

const STEPS = ['Файл', 'Проверка', 'Применение'] as const;
const VISIBLE_CHANGES = 20;

function Steps({ current }: { current: number }) {
  return (
    <ol className={styles.steps}>
      {STEPS.map((label, index) => {
        const state =
          index === current ? styles.stepActive : index < current ? styles.stepDone : '';
        return (
          <li
            key={label}
            className={`${styles.step} ${state}`}
            aria-current={index === current ? 'step' : undefined}
          >
            <span className={styles.stepNumber}>{index < current ? '✓' : index + 1}</span>
            <span className={styles.stepLabel}>
              Шаг {index + 1}. {label}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** До применения — план («создать»), после — факт («создано»). */
function SummaryCards({
  summary,
  applied = false,
}: {
  summary: ImportPreview['summary'];
  applied?: boolean;
}) {
  return (
    <div className={styles.summaryGrid}>
      {summaryRows(summary).map((row) => (
        <div key={row.key} className={styles.summaryCard}>
          <span className={styles.summaryTitle}>{row.label}</span>
          <span className={styles.summaryNumbers}>
            <span className={styles.createCount}>
              {applied ? 'создано' : 'создать'} <b>{formatCount(row.create)}</b>
            </span>
            <span className={styles.updateCount}>
              {applied ? 'изменено' : 'изменить'} <b>{formatCount(row.update)}</b>
            </span>
            <span className={styles.muted}>
              без изменений <b>{formatCount(row.unchanged)}</b>
            </span>
          </span>
        </div>
      ))}
    </div>
  );
}

type ImportWizardProps = {
  /** Импорт применён: историю и данные каталога нужно перечитать. */
  onCommitted: () => void;
};

export function ImportWizard({ onCommitted }: ImportWizardProps) {
  const { can } = useSession();
  const toast = useToast();
  const confirm = useConfirm();
  const inputRef = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [result, setResult] = useState<ImportCommitResult | null>(null);
  const [busy, setBusy] = useState<'preview' | 'commit' | null>(null);
  const [commitError, setCommitError] = useState<unknown>(null);
  const [visibleChanges, setVisibleChanges] = useState(VISIBLE_CHANGES);

  const canWrite = can(Permission.CATALOG_WRITE);
  const step = result ? 2 : preview ? 1 : 0;

  const pick = (next: File | null) => {
    setPreview(null);
    setResult(null);
    setCommitError(null);
    if (!next) {
      setFile(null);
      setFileError(null);
      return;
    }
    const problem = checkXlsxFile(next);
    setFileError(problem);
    setFile(problem ? null : next);
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    const dropped = event.dataTransfer?.files?.[0];
    if (dropped) pick(dropped);
  };

  const runPreview = async () => {
    if (!file) return;
    setBusy('preview');
    setCommitError(null);
    try {
      const report = await importsApi.preview(file);
      setPreview(report);
      setVisibleChanges(VISIBLE_CHANGES);
      if (report.valid) {
        toast.success('Файл проверен', 'Ошибок нет — можно применять.');
      } else {
        // show(): текст описания готов, describeError здесь не нужен.
        toast.show({
          tone: 'error',
          title: 'В файле есть ошибки',
          description: 'Исправьте их в книге и загрузите файл заново.',
        });
      }
    } catch (error) {
      toast.show({
        tone: 'error',
        title: 'Файл не принят',
        description: uploadErrorText(error) ?? describeError(error),
      });
    } finally {
      setBusy(null);
    }
  };

  const runCommit = async () => {
    if (!file || !preview) return;
    const counts = summaryRows(preview.summary)
      .filter((row) => row.create > 0 || row.update > 0)
      .map((row) => `${row.label.toLowerCase()}: +${row.create} / ${row.update}`)
      .join('; ');
    const agreed = await confirm({
      title: 'Применить импорт?',
      description: `Изменения применяются целиком, одной транзакцией, и отменить их нельзя. ${
        counts ? `Будет создано и изменено — ${counts}.` : 'Изменений в файле нет.'
      }`,
      confirmLabel: 'Применить',
      tone: 'primary',
    });
    if (!agreed) return;

    setBusy('commit');
    setCommitError(null);
    try {
      const applied = await importsApi.commit(preview.job.uuid, file);
      setResult(applied);
      toast.success('Импорт применён', 'Изменения записаны в каталог.');
      onCommitted();
    } catch (error) {
      setCommitError(error);
      toast.error('Импорт не применён', error);
    } finally {
      setBusy(null);
    }
  };

  const reset = () => {
    pick(null);
    if (inputRef.current) inputRef.current.value = '';
  };

  // ------------------------------------------------------------ шаг 3
  if (result) {
    return (
      <Card title="Импорт применён">
        <Steps current={step} />
        <div className={styles.section}>
          <div className={`${styles.banner} ${styles.bannerSuccess}`}>
            <span>
              <span className={styles.bannerTitle}>Каталог обновлён. </span>
              Обработано строк: {formatCount(result.job.rows_total)}. Создано товаров:{' '}
              {formatCount(result.job.products_created)}, изменено:{' '}
              {formatCount(result.job.products_updated)}.
            </span>
          </div>
          <SummaryCards summary={result.summary} applied />
          {(result.warnings ?? []).length > 0 ? (
            <IssueList
              title="Предупреждения"
              description="Импорт применён; на эти строки стоит взглянуть."
              items={result.warnings ?? []}
              total={result.job.warning_count}
              tone="warning"
              defaultOpen={false}
            />
          ) : null}
          <div className={styles.actions}>
            <ButtonLink href="/products" variant="primary" icon="products">
              Перейти к товарам
            </ButtonLink>
            <Button icon="refresh" onClick={reset}>
              Импортировать ещё файл
            </Button>
          </div>
        </div>
      </Card>
    );
  }

  // ------------------------------------------------------------ шаг 2
  if (preview) {
    const { job, summary } = preview;
    const changes = preview.changes.slice(0, visibleChanges);
    const hiddenChanges = preview.changes.length - changes.length;
    const nothingToDo = !hasChanges(summary);
    const blocked = !preview.valid || !job.can_commit;
    const commitIssues = issuesFromError(commitError);

    return (
      <Card
        title="Проверка файла"
        description={`${job.filename} · ${formatBytes(job.file_size)}`}
        actions={
          <Button icon="close" onClick={reset} disabled={busy !== null}>
            Выбрать другой файл
          </Button>
        }
      >
        <Steps current={step} />
        <div className={styles.section}>
          {preview.valid ? (
            <div className={`${styles.banner} ${styles.bannerSuccess}`}>
              <span>
                <span className={styles.bannerTitle}>Ошибок нет. </span>
                Проверено строк: {formatCount(preview.summary.rows_total)}. Изменений:{' '}
                {formatCount(totalChanges(summary))}.
              </span>
            </div>
          ) : (
            <div className={`${styles.banner} ${styles.bannerDanger}`}>
              <span>
                <span className={styles.bannerTitle}>Импорт применить нельзя. </span>
                {formatCount(preview.error_count)}{' '}
                {plural(preview.error_count, ['ошибка', 'ошибки', 'ошибок'])} в данных файла.
                Исправьте их в книге и загрузите файл заново.
              </span>
            </div>
          )}

          {nothingToDo && preview.valid ? (
            <div className={`${styles.banner} ${styles.bannerInfo}`}>
              <span>Файл совпадает с каталогом: применять нечего.</span>
            </div>
          ) : null}

          <SummaryCards summary={summary} />

          <IssueList
            title="Ошибки"
            description="Пока они не исправлены, импорт применить нельзя."
            items={preview.errors}
            total={preview.error_count}
            tone="error"
          />
          <IssueList
            title="Предупреждения"
            description="Применению не мешают, но стоит проверить."
            items={preview.warnings}
            total={preview.warning_count}
            tone="warning"
            defaultOpen={false}
          />

          {preview.changes.length > 0 ? (
            <section>
              <h3 className={styles.issuesTitle}>Что изменится у товаров</h3>
              <ul className={styles.changes}>
                {changes.map((change) => (
                  <li key={`${change.row}-${change.sku}`} className={styles.change}>
                    <span className={styles.changeSku}>{change.sku}</span>
                    <span className={styles.muted}>строка {change.row}</span>
                    <span>
                      {change.action === 'create'
                        ? 'новый товар'
                        : (change.changed ?? []).map(changePartLabel).join(', ') || 'без изменений'}
                    </span>
                  </li>
                ))}
              </ul>
              {hiddenChanges > 0 ? (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setVisibleChanges((value) => value + VISIBLE_CHANGES)}
                >
                  Показать ещё {formatCount(Math.min(hiddenChanges, VISIBLE_CHANGES))}
                </Button>
              ) : null}
              {preview.changes_truncated ? (
                <p className={styles.muted}>
                  Показаны первые {formatCount(preview.changes.length)} товаров — в файле их больше.
                </p>
              ) : null}
            </section>
          ) : null}

          {commitError ? (
            <div className={`${styles.banner} ${styles.bannerDanger}`} role="alert">
              <span>
                <span className={styles.bannerTitle}>Импорт не применён. </span>
                {describeError(commitError)}
              </span>
            </div>
          ) : null}
          {commitIssues.length > 0 ? (
            <IssueList
              title="Ошибки повторной проверки"
              description="Каталог изменился после предпросмотра. Загрузите файл заново."
              items={commitIssues}
              total={commitIssues.length}
              tone="error"
            />
          ) : null}

          <div className={styles.footerBar}>
            <span className={styles.muted}>
              {canWrite
                ? 'Применение изменит каталог целиком, одной транзакцией.'
                : 'Проверка не меняет каталог. Применять импорт может сотрудник с правом изменения каталога.'}
            </span>
            {canWrite ? (
              <Button
                variant="primary"
                icon="check"
                loading={busy === 'commit'}
                disabled={blocked || nothingToDo}
                onClick={() => void runCommit()}
              >
                Применить импорт
              </Button>
            ) : null}
          </div>
        </div>
      </Card>
    );
  }

  // ------------------------------------------------------------ шаг 1
  return (
    <Card title="Импорт каталога" description="Книга Excel .xlsx того же формата, что и экспорт.">
      <Steps current={step} />
      <div className={styles.section}>
        {file ? (
          <div className={styles.selectedFile}>
            <span className={styles.fileMeta}>
              <span className={styles.strong}>{file.name}</span>
              <span className={styles.muted}>{formatBytes(file.size)}</span>
            </span>
            <span className={styles.actions}>
              <Button
                variant="primary"
                icon="check"
                loading={busy === 'preview'}
                onClick={() => void runPreview()}
              >
                Проверить файл
              </Button>
              <Button variant="ghost" icon="close" onClick={reset} disabled={busy !== null}>
                Убрать
              </Button>
            </span>
          </div>
        ) : (
          <div
            className={`${styles.dropzone} ${dragging ? styles.dropzoneActive : ''}`}
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
          >
            <span className={styles.dropzoneTitle}>Перетащите файл .xlsx сюда</span>
            <span className={styles.muted}>
              или выберите его на диске (до {MAX_FILE_SIZE_MB} МБ)
            </span>
            <Button icon="plus" onClick={() => inputRef.current?.click()}>
              Выбрать файл
            </Button>
            <input
              ref={inputRef}
              type="file"
              accept={XLSX_ACCEPT}
              className={styles.fileInput}
              aria-label="Файл каталога в формате XLSX"
              onChange={(event) => pick(event.target.files?.[0] ?? null)}
            />
          </div>
        )}

        {fileError ? (
          <div className={`${styles.banner} ${styles.bannerDanger}`} role="alert">
            <span>{fileError}</span>
          </div>
        ) : null}

        <div>
          <p className={styles.hint}>Что умеет формат:</p>
          <ul className={styles.hintList}>
            <li>
              Листы Products, Prices, ProductAttributes, ProductSpecs, Categories,
              CategoryAttributes, Attributes, AttributeOptions.
            </li>
            <li>
              Ключи: товар — <span className="mono">sku</span>, категория —{' '}
              <span className="mono">slug</span>, характеристика —{' '}
              <span className="mono">code</span>.
            </li>
            <li>Строки создают и обновляют записи; удалить что-либо через импорт нельзя.</li>
            <li>
              Чего нет в файле — то не меняется. Сначала проверка, применение — отдельным шагом.
            </li>
          </ul>
        </div>
      </div>
    </Card>
  );
}
