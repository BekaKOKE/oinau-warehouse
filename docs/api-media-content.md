# Медиатека и CMS (этап 5D)

## Медиатека

Бинарные файлы в PostgreSQL не хранятся. `media_files` — только метаданные:
`storage_key`, `bucket`, `mime_type`, `size_bytes`, `original_filename`,
`width`/`height`, `checksum` (SHA-256), `status`, `failure_reason`,
`variants` (JSONB), `created_at`.

### Поток загрузки

```
1. POST /admin/media/upload-intent  {filename, content_type, size_bytes, purpose}
      -> запись PENDING + presigned PUT (файл идёт в хранилище мимо API)
2. PUT <upload.url> с заголовками upload.headers   (браузер -> R2/MinIO)
3. POST /admin/media/{uuid}/complete
      -> HEAD: объект есть, размер <= UPLOAD_MAX_SIZE_MB;
         сигнатура (magic bytes) = заявленный тип  -> PROCESSING + задача arq
         иначе FAILED (422 upload_rejected), объект удаляется
4. воркер process_media: Pillow декодирует файл заявленного формата,
   проверяет число пикселей, применяет EXIF-ориентацию и строит
   WebP-варианты large/medium/small/thumb (1600/800/400/200, без
   увеличения и без EXIF) -> READY | FAILED
```

Ключи объектов — только UUID, имя клиента в них не попадает:

```
products/{uuid}/original.png          приватно
products/{uuid}/variants/large.webp   публично, Cache-Control: immutable
content/{uuid}/...                    purpose=CONTENT (изображения CMS)
```

Префиксы совпадают с политикой бакета (`infra/docker/minio/init.sh`).
Код зависит от протокола `ObjectStorage` (`app/infrastructure/storage/base.py`),
реализация — S3 API (`s3.py`): R2 в проде, MinIO локально, без R2-специфичных вызовов.
`S3_PUBLIC_ENDPOINT_URL` — адрес для подписи presigned URL (локально `http://localhost:9000`).

Публичные ссылки строит одно правило (`app/modules/media/urls.py`) через
`build_public_url`: только READY и только варианты. Оригинал и `storage_key`
наружу не выходят, в том числе в админку.

### Эндпоинты

| Метод  | Путь                                                                        | Право                                        |
| ------ | --------------------------------------------------------------------------- | -------------------------------------------- |
| POST   | `/api/v1/admin/media/upload-intent`                                         | `catalog.write` + `media.upload`, rate limit |
| POST   | `/api/v1/admin/media/{uuid}/complete`                                       | `catalog.write` + `media.upload`             |
| GET    | `/api/v1/admin/media` (`status`, `search`, пагинация)                       | `catalog.read`                               |
| GET    | `/api/v1/admin/media/{uuid}` (+ где используется)                           | `catalog.read`                               |
| DELETE | `/api/v1/admin/media/{uuid}` — 409, если привязан к товару или CMS          | `catalog.write`                              |
| GET    | `/api/v1/admin/products/{id}/images`                                        | `catalog.read`                               |
| POST   | `/api/v1/admin/products/{id}/images` `{media_uuid, kind, alt, is_main}`     | `catalog.write`                              |
| PATCH  | `/api/v1/admin/products/{id}/images/{image_id}` `{kind, alt}`               | `catalog.write`                              |
| PUT    | `/api/v1/admin/products/{id}/images/order` `{image_ids}` — полный список    | `catalog.write`                              |
| PUT    | `/api/v1/admin/products/{id}/images/main` `{image_id}`                      | `catalog.write`                              |
| DELETE | `/api/v1/admin/products/{id}/images/{image_id}` — файл остаётся в медиатеке | `catalog.write`                              |

Правила галереи: удалённый товар только читается (`product_deleted`); FAILED
не привязывается; PENDING/PROCESSING привязать можно, витрина покажет файл
после READY; первое изображение становится главным, при отвязке главного
главным становится следующее; главное всегда одно (частичный уникальный индекс).

### Документы: схемы и чертежи

PDF, DWG и DXF — такие же файлы медиатеки (`UPLOAD_ALLOWED_DOCUMENT_MIME`,
лимит `UPLOAD_MAX_DOCUMENT_SIZE_MB`). Сигнатура проверяется при
`complete` и в воркере; вместо WebP-вариантов воркер кладёт публичную
копию `products/{uuid}/variants/file.<ext>` с `Content-Disposition`
(PDF — `inline`, DWG/DXF — `attachment`). Политика бакета не менялась:
публичны только `*/variants/*`. Документ привязывается к товару только
как `SCHEME`, `DRAWING` или `CERTIFICATE` и не может быть обложкой
(`409 document_kind_invalid`).

## CMS

Структурированный, не конструктор: одна строка `content_sections` на раздел,
данные — JSONB строго по Pydantic-схеме раздела (`extra="forbid"`).
Разделы: `home`, `contacts`, `delivery`, `faq`, `requisites`, `settings`, `services`.

`services` — услуги (обжимка и обрезка канатов, металлорезка, ...): вступление
и список `{slug, title, summary, details[], price_note, image, cta_label}`;
slug — якорь на странице `/services#slug`, уникален в разделе.

- Текст — только простой (`app/core/text.py`): без HTML, управляющих
  символов и bidi-override; абзацы — переводы строк.
- Ссылки — `https://`, `http://` или путь `/...`; `javascript:`, `data:`,
  `//host` отвергаются. Соцсети — только https.
- Локализация — `{"ru": "...", "kk": "..."}`; `ru` обязателен, `kk` можно
  заполнить заранее и включить через `SUPPORTED_LOCALES` без миграции.
- Изображения — UUID файлов медиатеки; удалить файл, упомянутый в CMS, нельзя.
- SEO каждой страницы: `title`, `description`, `og_title`, `og_description`,
  `og_image`; пустое поле берётся из SEO по умолчанию (`settings`).
- Реквизиты проверяются по формату РК: БИН (12 цифр), IBAN (KZ, контрольная
  сумма mod 97), БИК, КБе.

| Метод     | Путь                                                  | Доступ          |
| --------- | ----------------------------------------------------- | --------------- |
| GET       | `/api/v1/admin/content`                               | `content.write` |
| GET / PUT | `/api/v1/admin/content/{раздел}`                      | `content.write` |
| GET       | `/api/v1/public/content/home`                         | публично        |
| GET       | `/api/v1/public/content/contacts` (включая реквизиты) | публично        |
| GET       | `/api/v1/public/content/delivery`                     | публично        |
| GET       | `/api/v1/public/content/faq`                          | публично        |
| GET       | `/api/v1/public/content/services`                     | публично        |
| GET       | `/api/v1/public/content/settings` (шапка/подвал)      | публично        |

Все мутации медиатеки, галереи и CMS пишутся в `audit_log`.
