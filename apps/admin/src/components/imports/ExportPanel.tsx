'use client';

/**
 * Экспорт каталога в XLSX и пустой шаблон.
 *
 * Книгу собирает backend (GET /admin/catalog/export): в браузере она
 * не формируется — иначе форматы экспорта и импорта неизбежно
 * разъехались бы. Фильтров экспорта в API нет, выгружается весь живой
 * каталог, и об этом прямо сказано на экране.
 */

import { useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Layout';
import { useToast } from '@/components/ui/Toast';
import type { DownloadedFile } from '@/lib/api/client';
import { importsApi } from '@/lib/api/endpoints';
import { saveBlob } from '@/lib/download';

import styles from './ImportExport.module.css';

type Job = 'catalog' | 'template';

export function ExportPanel() {
  const toast = useToast();
  const [busy, setBusy] = useState<Job | null>(null);

  const download = async (job: Job, load: () => Promise<DownloadedFile>, fallback: string) => {
    setBusy(job);
    try {
      const file = await load();
      saveBlob(file.blob, file.filename ?? fallback);
      toast.success('Файл готов', 'Проверьте загрузки браузера.');
    } catch (error) {
      toast.error('Не удалось выгрузить файл', error);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card
      title="Экспорт каталога"
      description="Товары, категории, характеристики и цены публичного прайс-листа одной книгой."
    >
      <div className={styles.actions}>
        <Button
          variant="primary"
          icon="import"
          loading={busy === 'catalog'}
          disabled={busy !== null}
          onClick={() =>
            void download('catalog', () => importsApi.exportCatalog(), 'oinau-catalog.xlsx')
          }
        >
          Скачать каталог (XLSX)
        </Button>
        <Button
          icon="import"
          loading={busy === 'template'}
          disabled={busy !== null}
          onClick={() =>
            void download('template', () => importsApi.template(), 'oinau-catalog-template.xlsx')
          }
        >
          Пустой шаблон
        </Button>
      </div>
      <ul className={styles.hintList}>
        <li>Остатки, фото и схемы в эту книгу не входят — их загружает «Массовый импорт (ZIP)».</li>
        <li>Экспорт без правок можно загрузить обратно — изменений не будет.</li>
      </ul>
    </Card>
  );
}
