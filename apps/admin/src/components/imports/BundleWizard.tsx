'use client';

/**
 * Массовый импорт товаров: ZIP с products.xlsx, фото и схемами.
 *
 * Шаги: Файл → Проверка → Предпросмотр → Импорт → Отчёт. Архив
 * загружается прямо в хранилище (PUT по presigned-ссылке, с прогрессом),
 * проверку и применение выполняет воркер — экран опрашивает задачу,
 * пока статус не станет итоговым. Ничего не применяется сразу после
 * выбора файла: каталог меняется только по кнопке «Применить импорт».
 */

import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react';

import { useSession } from '@/components/session/SessionProvider';
import { Button, ButtonLink } from '@/components/ui/Button';
import { useConfirm } from '@/components/ui/Dialog';
import { Card } from '@/components/ui/Layout';
import { useToast } from '@/components/ui/Toast';
import type { DownloadedFile } from '@/lib/api/client';
import { bundleApi } from '@/lib/api/endpoints';
import type { BundleJob } from '@/lib/api/types';
import { Permission } from '@/lib/auth/permissions';
import {
  BUNDLE_STEPS,
  MAX_BUNDLE_SIZE_MB,
  POLL_INTERVAL_MS,
  ZIP_ACCEPT,
  bundleFigures,
  bundleStep,
  checkZipFile,
  isWorking,
} from '@/lib/bundle';
import { saveBlob } from '@/lib/download';
import { describeError } from '@/lib/errors';
import { formatBytes, formatCount } from '@/lib/format';
import { changePartLabel, failureText } from '@/lib/imports';
import { putToStorage } from '@/lib/media';

import { IssueList } from './IssueList';
import styles from './ImportExport.module.css';

const VISIBLE_CHANGES = 20;

function Steps({ current }: { current: number }) {
  return (
    <ol className={styles.steps}>
      {BUNDLE_STEPS.map((label, index) => {
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

function Figures({ job }: { job: BundleJob }) {
  return (
    <dl className={styles.figures}>
      {bundleFigures(job).map((figure) => (
        <div
          key={figure.key}
          className={`${styles.figure} ${figure.tone ? styles[`figure_${figure.tone}`] : ''}`}
        >
          <dt>{figure.label}</dt>
          <dd>{formatCount(figure.value)}</dd>
        </div>
      ))}
    </dl>
  );
}

type BundleWizardProps = {
  /** Импорт применён: история и данные каталога перечитываются. */
  onCommitted: () => void;
  /** Подменяются в тестах: jsdom не умеет настоящий PUT и ждать секундами. */
  put?: typeof putToStorage;
  pollMs?: number;
};

export function BundleWizard({
  onCommitted,
  put = putToStorage,
  pollMs = POLL_INTERVAL_MS,
}: BundleWizardProps) {
  const { can } = useSession();
  const toast = useToast();
  const confirm = useConfirm();
  const inputRef = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [job, setJob] = useState<BundleJob | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [busy, setBusy] = useState<'upload' | 'commit' | 'cancel' | 'report' | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [visibleChanges, setVisibleChanges] = useState(VISIBLE_CHANGES);
  const abortRef = useRef<AbortController | null>(null);
  const committedRef = useRef<string | null>(null);

  const canWrite = can(Permission.CATALOG_WRITE) && can(Permission.MEDIA_UPLOAD);
  const status = job?.status ?? null;
  const step = bundleStep(status);

  // Опрос задачи, пока воркер проверяет или применяет архив.
  useEffect(() => {
    if (!job || !isWorking(job.status) || busy === 'upload') return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      bundleApi
        .get(job.uuid, { signal: controller.signal })
        .then(setJob)
        .catch((error: unknown) => {
          if (controller.signal.aborted) return;
          setFailure(describeError(error));
        });
    }, pollMs);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [job, busy, pollMs]);

  // Применённый импорт меняет каталог — сообщить один раз.
  useEffect(() => {
    if (job?.status === 'COMMITTED' && committedRef.current !== job.uuid) {
      committedRef.current = job.uuid;
      toast.success('Импорт завершён', 'Товары, фото и схемы записаны в каталог.');
      onCommitted();
    }
  }, [job, onCommitted, toast]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const pick = (next: File | null) => {
    setFailure(null);
    if (!next) {
      setFile(null);
      setFileError(null);
      return;
    }
    const problem = checkZipFile(next);
    setFileError(problem);
    setFile(problem ? null : next);
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    const dropped = event.dataTransfer?.files?.[0];
    if (dropped) pick(dropped);
  };

  const upload = async () => {
    if (!file) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy('upload');
    setFailure(null);
    setProgress(0);
    try {
      const created = await bundleApi.create({ filename: file.name, size_bytes: file.size });
      setJob(created.job);
      await put(
        created.upload.url,
        created.upload.method,
        created.upload.headers,
        file,
        setProgress,
        controller.signal,
      );
      setJob(await bundleApi.check(created.job.uuid));
      setVisibleChanges(VISIBLE_CHANGES);
    } catch (error) {
      if (controller.signal.aborted) return;
      setFailure(describeError(error));
      toast.error('Архив не загружен', error);
    } finally {
      setBusy(null);
      setProgress(null);
    }
  };

  const commit = async () => {
    if (!job) return;
    const agreed = await confirm({
      title: 'Применить импорт?',
      description:
        `Будет создано товаров: ${formatCount(job.products_created)}, обновлено: ` +
        `${formatCount(job.products_updated)}. Новые фото и схемы загрузятся в медиатеку. ` +
        'Изменения применяются целиком, одной транзакцией.',
      confirmLabel: 'Применить',
      tone: 'primary',
    });
    if (!agreed) return;
    setBusy('commit');
    setFailure(null);
    try {
      setJob(await bundleApi.commit(job.uuid));
    } catch (error) {
      setFailure(describeError(error));
      toast.error('Импорт не запущен', error);
    } finally {
      setBusy(null);
    }
  };

  const cancel = async () => {
    abortRef.current?.abort();
    if (!job) {
      reset();
      return;
    }
    const agreed = await confirm({
      title: 'Отменить импорт?',
      description: 'Архив будет удалён, каталог не изменится.',
      confirmLabel: 'Отменить импорт',
      tone: 'danger',
    });
    if (!agreed) return;
    setBusy('cancel');
    try {
      if (job.can_cancel || isWorking(job.status)) await bundleApi.cancel(job.uuid);
      toast.success('Импорт отменён', 'Каталог не изменялся.');
      reset();
    } catch (error) {
      toast.error('Не удалось отменить импорт', error);
    } finally {
      setBusy(null);
    }
  };

  const downloadReport = useCallback(async () => {
    if (!job) return;
    setBusy('report');
    try {
      const report: DownloadedFile = await bundleApi.report(job.uuid);
      saveBlob(report.blob, report.filename ?? 'oinau-import-report.xlsx');
    } catch (error) {
      toast.error('Не удалось скачать отчёт', error);
    } finally {
      setBusy(null);
    }
  }, [job, toast]);

  const download = async (load: () => Promise<DownloadedFile>, fallback: string) => {
    try {
      const result = await load();
      saveBlob(result.blob, result.filename ?? fallback);
    } catch (error) {
      toast.error('Не удалось скачать файл', error);
    }
  };

  function reset() {
    setJob(null);
    setFile(null);
    setFileError(null);
    setFailure(null);
    setProgress(null);
    if (inputRef.current) inputRef.current.value = '';
  }

  const templateButtons = (
    <div className={styles.actions}>
      <Button
        icon="import"
        onClick={() => void download(() => bundleApi.template(), 'products.xlsx')}
      >
        Скачать шаблон Excel
      </Button>
      <Button
        icon="import"
        onClick={() => void download(() => bundleApi.example(), 'oinau-import-example.zip')}
      >
        Скачать пример ZIP
      </Button>
    </div>
  );

  // ------------------------------------------------------- 5. отчёт
  if (job && (job.status === 'COMMITTED' || job.status === 'FAILED')) {
    const ok = job.status === 'COMMITTED';
    return (
      <Card title={ok ? 'Импорт завершён' : 'Импорт не применён'} description={job.filename}>
        <Steps current={step} />
        <div className={styles.section}>
          <div className={`${styles.banner} ${ok ? styles.bannerSuccess : styles.bannerDanger}`}>
            <span>
              <span className={styles.bannerTitle}>
                {ok ? 'Каталог обновлён. ' : `${failureText(job.failure_code)}. `}
              </span>
              {ok
                ? 'Фото и схемы обрабатываются и появятся на сайте в течение минуты.'
                : 'Каталог не изменился: изменения откатываются целиком.'}
            </span>
          </div>
          <Figures job={job} />
          <IssueList title="Ошибки" items={job.errors ?? []} total={job.error_count} tone="error" />
          <IssueList
            title="Предупреждения"
            items={job.warnings ?? []}
            total={job.warning_count}
            tone="warning"
            defaultOpen={false}
          />
          <div className={styles.actions}>
            <Button
              variant="primary"
              icon="import"
              loading={busy === 'report'}
              onClick={() => void downloadReport()}
            >
              Скачать отчёт
            </Button>
            {ok ? (
              <ButtonLink href="/products" icon="products">
                Перейти к товарам
              </ButtonLink>
            ) : null}
            <Button icon="refresh" onClick={reset}>
              Импортировать ещё
            </Button>
          </div>
        </div>
      </Card>
    );
  }

  // ------------------------------------------ 2–4. проверка / импорт
  if (job && job.status !== 'VALID' && job.status !== 'INVALID' && job.status !== 'CANCELLED') {
    const applying = job.status === 'APPLYING';
    return (
      <Card title={applying ? 'Импорт' : 'Проверка архива'} description={job.filename}>
        <Steps current={step} />
        <div className={styles.section}>
          <div className={`${styles.banner} ${styles.bannerInfo}`} role="status">
            <span>
              {busy === 'upload' && progress !== null
                ? `Загрузка архива: ${progress}%`
                : applying
                  ? 'Применяем изменения: загружаем фото и схемы, записываем товары…'
                  : 'Проверяем архив: книгу, артикулы, категории, цены, файлы…'}
            </span>
          </div>
          {busy === 'upload' && progress !== null ? (
            <progress className={styles.progress} max={100} value={progress}>
              {progress}%
            </progress>
          ) : null}
          {failure ? (
            <div className={`${styles.banner} ${styles.bannerDanger}`} role="alert">
              <span>{failure}</span>
            </div>
          ) : null}
          {!applying ? (
            <div className={styles.actions}>
              <Button icon="close" onClick={() => void cancel()} disabled={busy === 'cancel'}>
                Отменить импорт
              </Button>
            </div>
          ) : null}
        </div>
      </Card>
    );
  }

  // ------------------------------------------------- 3. предпросмотр
  if (job && (job.status === 'VALID' || job.status === 'INVALID')) {
    const valid = job.status === 'VALID';
    const changes = (job.changes ?? []).slice(0, visibleChanges);
    const hidden = (job.changes ?? []).length - changes.length;
    return (
      <Card
        title="Предпросмотр импорта"
        description={`${job.filename} · ${formatBytes(job.file_size)}`}
      >
        <Steps current={step} />
        <div className={styles.section}>
          <div className={`${styles.banner} ${valid ? styles.bannerSuccess : styles.bannerDanger}`}>
            <span>
              <span className={styles.bannerTitle}>
                {valid ? 'Ошибок нет. ' : 'Импорт применить нельзя. '}
              </span>
              {valid
                ? 'Проверьте изменения и примените импорт — до этого каталог не меняется.'
                : 'Исправьте ошибки в книге или архиве и загрузите его заново.'}
            </span>
          </div>

          <Figures job={job} />

          <IssueList
            title="Ошибки"
            description="Пока они не исправлены, импорт применить нельзя."
            items={job.errors ?? []}
            total={job.error_count}
            tone="error"
          />
          <IssueList
            title="Предупреждения"
            description="Применению не мешают, но стоит проверить."
            items={job.warnings ?? []}
            total={job.warning_count}
            tone="warning"
            defaultOpen={false}
          />

          {changes.length > 0 ? (
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
                        : (change.changed ?? []).map(changePartLabel).join(', ')}
                    </span>
                  </li>
                ))}
              </ul>
              {hidden > 0 ? (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setVisibleChanges((value) => value + VISIBLE_CHANGES)}
                >
                  Показать ещё {formatCount(Math.min(hidden, VISIBLE_CHANGES))}
                </Button>
              ) : null}
            </section>
          ) : null}

          {failure ? (
            <div className={`${styles.banner} ${styles.bannerDanger}`} role="alert">
              <span>{failure}</span>
            </div>
          ) : null}

          <div className={styles.footerBar}>
            <span className={styles.actions}>
              <Button
                icon="import"
                loading={busy === 'report'}
                onClick={() => void downloadReport()}
              >
                Скачать отчёт
              </Button>
              <Button icon="close" onClick={() => void cancel()} disabled={busy !== null}>
                Отменить импорт
              </Button>
            </span>
            {canWrite ? (
              <Button
                variant="primary"
                icon="check"
                loading={busy === 'commit'}
                disabled={!valid || !job.can_commit || busy !== null}
                onClick={() => void commit()}
              >
                Применить импорт
              </Button>
            ) : null}
          </div>
        </div>
      </Card>
    );
  }

  // ------------------------------------------------------- 1. файл
  return (
    <Card
      title="Массовый импорт товаров"
      description="ZIP-архив: products.xlsx, папка photos/ с фотографиями и schemes/ со схемами."
    >
      <Steps current={0} />
      <div className={styles.section}>
        {templateButtons}

        {!canWrite ? (
          <div className={`${styles.banner} ${styles.bannerInfo}`}>
            <span>
              Загружать архивы может сотрудник с правом изменения каталога и загрузки файлов.
            </span>
          </div>
        ) : file ? (
          <div className={styles.selectedFile}>
            <span className={styles.fileMeta}>
              <span className={styles.strong}>{file.name}</span>
              <span className={styles.muted}>{formatBytes(file.size)}</span>
            </span>
            <span className={styles.actions}>
              <Button
                variant="primary"
                icon="check"
                loading={busy === 'upload'}
                onClick={() => void upload()}
              >
                Загрузить и проверить
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
            <span className={styles.dropzoneTitle}>Перетащите ZIP-архив сюда</span>
            <span className={styles.muted}>
              или выберите его на диске (до {formatCount(MAX_BUNDLE_SIZE_MB)} МБ)
            </span>
            <Button icon="plus" onClick={() => inputRef.current?.click()}>
              Загрузить ZIP
            </Button>
            <input
              ref={inputRef}
              type="file"
              accept={ZIP_ACCEPT}
              className={styles.fileInput}
              aria-label="ZIP-архив с каталогом"
              onChange={(event) => pick(event.target.files?.[0] ?? null)}
            />
          </div>
        )}

        {fileError || failure ? (
          <div className={`${styles.banner} ${styles.bannerDanger}`} role="alert">
            <span>{fileError ?? failure}</span>
          </div>
        ) : null}

        <div>
          <p className={styles.hint}>Как устроен архив:</p>
          <ul className={styles.hintList}>
            <li>
              <span className="mono">products.xlsx</span> — лист «Товары»: Артикул, Название,
              Категория, Цена или «Цена от N», Остаток, Фото, Схема, «хар: …».
            </li>
            <li>
              <span className="mono">photos/</span> — фото (jpg, png, webp);{' '}
              <span className="mono">schemes/</span> — схемы (pdf, dwg, dxf, jpg, png).
            </li>
            <li>
              Ключ — артикул: существующий товар обновляется, новый создаётся. Пустая ячейка —
              значение не меняется.
            </li>
            <li>
              Фото через «;»: первое — обложка. Уже загруженные файлы повторно не загружаются.
            </li>
          </ul>
        </div>
      </div>
    </Card>
  );
}
