/**
 * Сохранение файла, полученного от API.
 *
 * Ссылка на API напрямую не годится: запрос требует заголовка
 * Authorization, а тег <a> его не отправляет. Файл забирается обычным
 * запросом и отдаётся браузеру через временный object URL.
 */

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.rel = 'noopener';
  document.body.append(link);
  link.click();
  link.remove();
  // Освобождаем память после того, как браузер начал скачивание.
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
