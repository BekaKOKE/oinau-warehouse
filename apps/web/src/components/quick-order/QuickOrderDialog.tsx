/**
 * Окно «Быстрый заказ».
 *
 * Три вкладки — три способа описать потребность без корзины:
 *   «По телефону»   — контакты и комментарий; с карточки товара это
 *                     «заказ в 1 клик» с одной позицией;
 *   «По артикулам»  — вставленный список, разбирает сервер;
 *   «Запрос КП»     — спецификация файлом и/или описанием.
 *
 * Контакты общие для всех вкладок: переключение вкладки не стирает
 * введённое. Проверка повторяет правила backend ровно настолько, чтобы
 * не отправлять заведомо неверную форму; последнее слово — за сервером,
 * его сообщения показываются как есть.
 */

'use client';

import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';

import type { QuickRequestCreated, QuickRequestMode } from '@oinau/api-types';

import { useCustomerSession } from '@/components/cabinet/CustomerSessionProvider';
import { Button } from '@/components/ui/Button';
import { TextAreaField, TextField } from '@/components/ui/Field';
import { useModalDialog } from '@/components/ui/useModalDialog';
import { ApiError, describeError } from '@/lib/api/client';
import {
  ATTACHMENT_MAX_MB,
  checkAttachment,
  submitQuickRequest,
  type QuickRequestInput,
} from '@/lib/api/quick-requests';
import { newIdempotencyKey } from '@/lib/api/requests';
import { describeItemError, minimumFromError } from '@/lib/request-errors';
import { currencySymbol, formatAmount, formatQuantity, plural, unitLabel } from '@/lib/format';
import { useQuickOrder, type QuickOrderOptions } from './QuickOrderContext';
import styles from './QuickOrderDialog.module.css';

const TABS: { mode: QuickRequestMode; label: string }[] = [
  { mode: 'CALLBACK', label: 'По телефону' },
  { mode: 'SKU_LIST', label: 'По артикулам' },
  { mode: 'QUOTE', label: 'Запрос КП' },
];

type Values = {
  name: string;
  phone: string;
  email: string;
  company: string;
  bin: string;
  comment: string;
  skuList: string;
  quantity: string;
};

type FieldName = keyof Values | 'file';
type FieldErrors = Partial<Record<FieldName, string>>;

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function validate(
  mode: QuickRequestMode,
  values: Values,
  file: File | null,
  /** undefined — не «в 1 клик»; null — минимальная партия неизвестна. */
  minQuantity: number | null | undefined,
): FieldErrors {
  const errors: FieldErrors = {};
  if (!values.name.trim()) errors.name = 'Укажите, как к вам обращаться';
  const digits = values.phone.match(/\d/g)?.length ?? 0;
  if (!values.phone.trim()) errors.phone = 'Укажите телефон для связи';
  else if (digits < 5 || digits > 15) errors.phone = 'В номере должно быть от 5 до 15 цифр';
  if (values.email.trim() && !EMAIL.test(values.email.trim())) {
    errors.email = 'Проверьте адрес электронной почты';
  }

  // Пустое количество допустимо, только если минимум неизвестен:
  // сервер подставит минимальную партию сам.
  if (mode === 'CALLBACK' && minQuantity !== undefined && values.quantity.trim()) {
    const quantity = Number(values.quantity.replace(',', '.'));
    if (!Number.isFinite(quantity) || quantity <= 0) errors.quantity = 'Укажите количество';
    else if (minQuantity !== null && quantity < minQuantity) {
      errors.quantity = `Минимальная партия — ${formatQuantity(String(minQuantity))}`;
    }
  } else if (mode === 'CALLBACK' && typeof minQuantity === 'number') {
    errors.quantity = 'Укажите количество';
  }
  if (mode === 'SKU_LIST' && !values.skuList.trim()) {
    errors.skuList = 'Вставьте хотя бы один артикул';
  }
  if (mode === 'QUOTE') {
    if (!values.email.trim()) errors.email = 'На этот адрес придёт коммерческое предложение';
    if (values.bin.trim() && !/^\d{12}$/.test(values.bin.replace(/\s/g, ''))) {
      errors.bin = 'БИН — 12 цифр';
    }
    if (!file && !values.comment.trim()) {
      errors.comment = 'Приложите файл или опишите, что нужно';
    }
  }
  return errors;
}

/** Ошибки полей из ответа 422: backend называет поле в `loc`. */
const SERVER_FIELDS: Record<string, FieldName> = {
  name: 'name',
  phone: 'phone',
  email: 'email',
  company: 'company',
  bin: 'bin',
  comment: 'comment',
  sku_list: 'skuList',
  quantity: 'quantity',
};

function serverFieldErrors(error: ApiError): FieldErrors {
  // «1 клик» из списка каталога не знает минимальной партии: в списке
  // API её не отдаёт, и проверить количество заранее нельзя. Минимум
  // приходит только в ответе — показываем его у поля количества.
  const minimum = minimumFromError(error);
  if (minimum !== null) return { quantity: `Минимальная партия — ${minimum}` };

  const fields = error.details?.fields;
  if (!Array.isArray(fields)) return {};
  const errors: FieldErrors = {};
  for (const entry of fields) {
    if (typeof entry !== 'object' || entry === null) continue;
    const { loc, msg } = entry as { loc?: unknown[]; msg?: unknown };
    const key = Array.isArray(loc) ? String(loc[loc.length - 1] ?? '') : '';
    const field = SERVER_FIELDS[key];
    if (field && typeof msg === 'string') errors[field] = msg.replace(/^Value error, /, '');
  }
  return errors;
}

function describeSubmitError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'validation_error') {
      const fields = error.details?.fields;
      const first = Array.isArray(fields) ? (fields[0] as { msg?: unknown } | undefined) : null;
      if (first && typeof first.msg === 'string') return first.msg.replace(/^Value error, /, '');
    }
    // Недоступный товар, количество ниже минимальной партии и слишком
    // частые обращения объясняются так же, как в корзине.
    return describeItemError(error);
  }
  return describeError(error);
}

function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} КБ`;
  return `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} МБ`;
}

export function QuickOrderDialog() {
  const { isOpen, options, session, close } = useQuickOrder();
  if (!isOpen) return null;
  // Новое открытие — новая форма: key сбрасывает состояние и ключ
  // идемпотентности, а предыдущий ответ не показывается повторно.
  return <QuickOrderPanel key={session} options={options} onClose={close} />;
}

function QuickOrderPanel({
  options,
  onClose,
}: {
  options: QuickOrderOptions;
  onClose: () => void;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  useModalDialog(panelRef, true, onClose);

  const titleId = useId();
  const tabsId = useId();
  const { status: sessionStatus, profile } = useCustomerSession();
  const signedIn = sessionStatus === 'authenticated' && profile !== null;

  const product = options.product ?? null;
  const [mode, setMode] = useState<QuickRequestMode>(
    options.mode ?? (options.skuList ? 'SKU_LIST' : 'CALLBACK'),
  );
  const [values, setValues] = useState<Values>({
    name: '',
    phone: '',
    email: '',
    company: '',
    bin: '',
    comment: options.comment ?? '',
    skuList: options.skuList ?? '',
    quantity: String(product?.quantity ?? product?.minOrderQty ?? ''),
  });
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<QuickRequestCreated | null>(null);
  const idempotencyKey = useRef(newIdempotencyKey());
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  // Профиль приходит после восстановления сессии — заполняем только
  // пустые поля, чтобы не затереть то, что человек уже ввёл.
  useEffect(() => {
    if (!profile) return;
    setValues((current) => ({
      ...current,
      name: current.name || profile.contact_name,
      phone: current.phone || profile.phone,
      email: current.email || profile.email,
      company: current.company || (profile.company_name ?? ''),
    }));
  }, [profile]);

  const set = (key: keyof Values) => (value: string) => {
    setValues((current) => ({ ...current, [key]: value }));
    if (errors[key]) setErrors((current) => ({ ...current, [key]: undefined }));
  };

  function chooseFile(next: File | null) {
    setFormError(null);
    if (!next) {
      setFile(null);
      return;
    }
    const problem = checkAttachment(next);
    setErrors((current) => ({ ...current, file: problem ?? undefined, comment: undefined }));
    setFile(problem ? null : next);
  }

  function onTabKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const next = TABS[(index + step + TABS.length) % TABS.length];
    if (!next) return;
    setMode(next.mode);
    tabRefs.current[next.mode]?.focus();
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    const oneClick = mode === 'CALLBACK' && product !== null;
    const found = validate(
      mode,
      values,
      file,
      oneClick ? (product.minOrderQty ?? null) : undefined,
    );
    setErrors(found);
    if (Object.keys(found).length > 0) return;

    const input: QuickRequestInput = {
      mode,
      name: values.name,
      phone: values.phone,
      email: values.email,
      company: values.company,
      comment: mode === 'SKU_LIST' ? '' : values.comment,
      pageUrl: window.location.href.slice(0, 1000),
    };
    if (oneClick) {
      input.productSku = product.sku;
      input.productColor = product.color;
      input.quantity = values.quantity.replace(',', '.');
    }
    if (mode === 'SKU_LIST') input.skuList = values.skuList;
    if (mode === 'QUOTE') {
      input.bin = values.bin.replace(/\s/g, '');
      input.file = file;
    }

    setPending(true);
    try {
      setResult(await submitQuickRequest(input, idempotencyKey.current, { signedIn }));
    } catch (error) {
      if (error instanceof ApiError) setErrors(serverFieldErrors(error));
      setFormError(describeSubmitError(error));
      // Новая попытка после ошибки — новая заявка, а не повтор прежней.
      idempotencyKey.current = newIdempotencyKey();
    } finally {
      setPending(false);
    }
  }

  return (
    <div
      className={styles.overlay}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        ref={panelRef}
      >
        <header className={styles.header}>
          <div>
            <h2 className={styles.title} id={titleId}>
              {result ? 'Заявка отправлена' : 'Быстрый заказ'}
            </h2>
            <p className={styles.subtitle}>Менеджер свяжется с вами в рабочее время</p>
          </div>
          <button
            type="button"
            className={styles.close}
            onClick={onClose}
            aria-label="Закрыть окно быстрого заказа"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
              <path d="M2 2l10 10M12 2 2 12" stroke="currentColor" strokeWidth="1.8" />
            </svg>
          </button>
        </header>

        {result ? (
          <SubmittedView result={result} onClose={onClose} />
        ) : (
          <>
            <div className={styles.tabs} role="tablist" aria-label="Способ заказа">
              {TABS.map((tab, index) => {
                const selected = tab.mode === mode;
                return (
                  <button
                    key={tab.mode}
                    ref={(node) => {
                      tabRefs.current[tab.mode] = node;
                    }}
                    type="button"
                    role="tab"
                    id={`${tabsId}-${tab.mode}`}
                    aria-selected={selected}
                    aria-controls={`${tabsId}-panel`}
                    tabIndex={selected ? 0 : -1}
                    className={selected ? `${styles.tab} ${styles.tabActive}` : styles.tab}
                    onClick={() => setMode(tab.mode)}
                    onKeyDown={(event) => onTabKeyDown(event, index)}
                  >
                    {tab.label}
                  </button>
                );
              })}
            </div>

            <form
              className={styles.body}
              id={`${tabsId}-panel`}
              role="tabpanel"
              aria-labelledby={`${tabsId}-${mode}`}
              onSubmit={handleSubmit}
              noValidate
            >
              {mode === 'CALLBACK' ? (
                <>
                  {product ? (
                    <div className={styles.product}>
                      <div className={styles.productThumb} aria-hidden="true">
                        {product.imageUrl ? (
                          // Миниатюра из медиатеки — обычный <img>, как в корзине.
                          // eslint-disable-next-line @next/next/no-img-element
                          <img src={product.imageUrl} alt="" />
                        ) : (
                          <span>{product.sku}</span>
                        )}
                      </div>
                      <div className={styles.productBody}>
                        <p className={styles.productName}>{product.name}</p>
                        <p className={styles.productMeta}>
                          арт. {product.sku}
                          {product.colorName ? ` · цвет: ${product.colorName}` : ''} ·{' '}
                          {product.priceLabel}
                        </p>
                      </div>
                      <div className={styles.productQty}>
                        <TextField
                          label={`Кол-во, ${unitLabel(product.unit)}`}
                          name="quantity"
                          inputMode="decimal"
                          placeholder={product.minOrderQty ? undefined : 'мин. партия'}
                          value={values.quantity}
                          error={errors.quantity}
                          onChange={(event) => set('quantity')(event.target.value)}
                        />
                      </div>
                    </div>
                  ) : null}
                  <p className={styles.info}>
                    {product
                      ? 'Заказ в 1 клик: менеджер перезвонит, подтвердит наличие, цену и срок отгрузки.'
                      : 'Оставьте телефон — подберём позиции, рассчитаем цену и доставку.'}
                  </p>
                  <div className={styles.row}>
                    <TextField
                      label="Телефон"
                      required
                      name="phone"
                      type="tel"
                      autoComplete="tel"
                      placeholder="+7 7__ ___ __ __"
                      data-autofocus
                      value={values.phone}
                      error={errors.phone}
                      onChange={(event) => set('phone')(event.target.value)}
                    />
                    <TextField
                      label="Имя"
                      required
                      name="name"
                      autoComplete="name"
                      value={values.name}
                      error={errors.name}
                      onChange={(event) => set('name')(event.target.value)}
                    />
                  </div>
                  <TextField
                    label="Компания"
                    name="company"
                    autoComplete="organization"
                    value={values.company}
                    onChange={(event) => set('company')(event.target.value)}
                  />
                  <TextAreaField
                    label="Комментарий"
                    name="comment"
                    rows={3}
                    placeholder="Что нужно и в каком количестве"
                    value={values.comment}
                    error={errors.comment}
                    onChange={(event) => set('comment')(event.target.value)}
                  />
                </>
              ) : null}

              {mode === 'SKU_LIST' ? (
                <>
                  <p className={styles.info}>
                    Вставьте список артикулов с количеством — по строке на позицию. Распознаем
                    позиции и пришлём счёт; то, чего нет в каталоге, уточнит менеджер.
                  </p>
                  <TextAreaField
                    label="Артикулы и количество"
                    required
                    name="sku_list"
                    rows={6}
                    className={styles.skuList}
                    placeholder={'KAN-16-PP × 20\nKRP-M10 × 100'}
                    hint="Подойдёт копия из Excel или письма: «артикул × количество», «артикул 20 шт»"
                    data-autofocus
                    spellCheck={false}
                    value={values.skuList}
                    error={errors.skuList}
                    onChange={(event) => set('skuList')(event.target.value)}
                  />
                  <div className={styles.row}>
                    <TextField
                      label="Имя"
                      required
                      name="name"
                      autoComplete="name"
                      value={values.name}
                      error={errors.name}
                      onChange={(event) => set('name')(event.target.value)}
                    />
                    <TextField
                      label="Телефон"
                      required
                      name="phone"
                      type="tel"
                      autoComplete="tel"
                      value={values.phone}
                      error={errors.phone}
                      onChange={(event) => set('phone')(event.target.value)}
                    />
                  </div>
                  <TextField
                    label="Email для счёта"
                    name="email"
                    type="email"
                    autoComplete="email"
                    value={values.email}
                    error={errors.email}
                    onChange={(event) => set('email')(event.target.value)}
                  />
                </>
              ) : null}

              {mode === 'QUOTE' ? (
                <>
                  <p className={styles.info}>
                    Загрузите спецификацию или ТЗ — подготовим коммерческое предложение с оптовыми
                    ценами.
                  </p>
                  <div className={styles.dropField}>
                    <label
                      className={[
                        styles.drop,
                        dragging ? styles.dropActive : '',
                        errors.file ? styles.dropInvalid : '',
                      ]
                        .filter(Boolean)
                        .join(' ')}
                      onDragOver={(event) => {
                        event.preventDefault();
                        setDragging(true);
                      }}
                      onDragLeave={() => setDragging(false)}
                      onDrop={(event) => {
                        event.preventDefault();
                        setDragging(false);
                        chooseFile(event.dataTransfer.files[0] ?? null);
                      }}
                    >
                      <input
                        type="file"
                        name="file"
                        className={styles.fileInput}
                        accept=".pdf,.xls,.xlsx,.doc,.docx,.dwg,.dxf,.csv,.jpg,.jpeg,.png"
                        aria-describedby={errors.file ? `${tabsId}-file-error` : undefined}
                        data-autofocus
                        onChange={(event) => {
                          chooseFile(event.target.files?.[0] ?? null);
                          event.target.value = '';
                        }}
                      />
                      {file ? (
                        <span className={styles.dropFile}>
                          <span className={styles.dropFileName}>{file.name}</span>
                          <span className={styles.dropHint}>
                            {formatSize(file.size)} · нажмите, чтобы выбрать другой
                          </span>
                        </span>
                      ) : (
                        <span className={styles.dropEmpty}>
                          <span className={styles.dropTitle}>
                            Перетащите файл сюда или выберите на устройстве
                          </span>
                          <span className={styles.dropHint}>
                            PDF, Excel, Word, DWG, DXF, CSV, JPG, PNG — до {ATTACHMENT_MAX_MB} МБ
                          </span>
                        </span>
                      )}
                    </label>
                    {file ? (
                      <button
                        type="button"
                        className={styles.dropRemove}
                        onClick={() => chooseFile(null)}
                      >
                        Убрать файл
                      </button>
                    ) : null}
                    {errors.file ? (
                      <span className={styles.error} id={`${tabsId}-file-error`} role="alert">
                        {errors.file}
                      </span>
                    ) : null}
                  </div>
                  <TextAreaField
                    label="Что нужно"
                    name="comment"
                    rows={3}
                    placeholder="Объект, сроки, количество — если файла нет, опишите задачу здесь"
                    value={values.comment}
                    error={errors.comment}
                    onChange={(event) => set('comment')(event.target.value)}
                  />
                  <div className={styles.row}>
                    <TextField
                      label="Компания"
                      name="company"
                      autoComplete="organization"
                      value={values.company}
                      onChange={(event) => set('company')(event.target.value)}
                    />
                    <TextField
                      label="БИН"
                      name="bin"
                      inputMode="numeric"
                      maxLength={14}
                      value={values.bin}
                      error={errors.bin}
                      onChange={(event) => set('bin')(event.target.value)}
                    />
                  </div>
                  <div className={styles.row}>
                    <TextField
                      label="Имя"
                      required
                      name="name"
                      autoComplete="name"
                      value={values.name}
                      error={errors.name}
                      onChange={(event) => set('name')(event.target.value)}
                    />
                    <TextField
                      label="Телефон"
                      required
                      name="phone"
                      type="tel"
                      autoComplete="tel"
                      value={values.phone}
                      error={errors.phone}
                      onChange={(event) => set('phone')(event.target.value)}
                    />
                  </div>
                  <TextField
                    label="Email"
                    required
                    name="email"
                    type="email"
                    autoComplete="email"
                    value={values.email}
                    error={errors.email}
                    onChange={(event) => set('email')(event.target.value)}
                  />
                </>
              ) : null}

              {signedIn ? (
                <p className={styles.note}>
                  Контакты взяты из профиля. Заявка появится в кабинете, в разделе «Заявки».
                </p>
              ) : null}

              {formError ? (
                <p className={styles.formError} role="alert">
                  {formError}
                </p>
              ) : null}

              <Button type="submit" size="lg" block disabled={pending}>
                {pending ? 'Отправляем…' : 'Отправить заявку'}
              </Button>
              <p className={styles.note}>
                Нажимая кнопку, вы соглашаетесь на обработку контактных данных для ответа на заявку.
                Оплаты на сайте нет — менеджер выставит счёт.
              </p>
            </form>
          </>
        )}
      </div>
    </div>
  );
}

function SubmittedView({ result, onClose }: { result: QuickRequestCreated; onClose: () => void }) {
  const items = result.items ?? [];
  const unrecognized = result.unrecognized ?? [];
  const belowMinimum = result.below_minimum ?? [];
  const closeRef = useRef<HTMLButtonElement>(null);

  // Кнопка отправки исчезла вместе с формой — фокус переходит на
  // «Закрыть», а не теряется на <body>.
  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  return (
    <div className={styles.success}>
      <div className={styles.successMark} aria-hidden="true">
        ✓
      </div>
      <p className={styles.successText}>
        Номер заявки <strong>{result.number}</strong>. Менеджер свяжется с вами в рабочее время и
        подтвердит наличие, цены и сроки.
      </p>

      {items.length > 0 ? (
        <div className={styles.summary}>
          <p className={styles.summaryTitle}>
            {items.length} {plural(items.length, ['позиция', 'позиции', 'позиций'])} в заявке
            {result.total_estimate
              ? ` · предварительно ${formatAmount(result.total_estimate)} ${currencySymbol(result.currency)}`
              : ''}
          </p>
          <ul className={styles.summaryList}>
            {items.map((item) => (
              <li key={`${item.sku}:${item.color ?? ''}`}>
                <span className={styles.summarySku}>{item.sku}</span>
                <span className={styles.summaryName}>
                  {item.color_name ? `${item.name}, ${item.color_name}` : item.name}
                </span>
                <span className={styles.summaryQty}>
                  {formatQuantity(item.quantity)} {unitLabel(item.unit)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {unrecognized.length > 0 ? (
        <div className={`${styles.summary} ${styles.summaryWarn}`}>
          <p className={styles.summaryTitle}>Не нашли в каталоге — менеджер уточнит:</p>
          <ul className={styles.summaryList}>
            {unrecognized.map((line) => (
              <li key={line}>
                <span className={styles.summaryName}>{line}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {belowMinimum.length > 0 ? (
        <div className={`${styles.summary} ${styles.summaryWarn}`}>
          <p className={styles.summaryTitle}>Меньше минимальной партии — количество согласуем:</p>
          <ul className={styles.summaryList}>
            {belowMinimum.map((item) => (
              <li key={item.sku}>
                <span className={styles.summarySku}>{item.sku}</span>
                <span className={styles.summaryName}>
                  {formatQuantity(item.quantity)} при минимуме {formatQuantity(item.min_order_qty)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {result.attachment ? (
        <p className={styles.successText}>
          Файл «{result.attachment.filename}» ({formatSize(result.attachment.size_bytes)}) получен.
        </p>
      ) : null}

      <Button variant="dark" size="lg" onClick={onClose} ref={closeRef}>
        Закрыть
      </Button>
    </div>
  );
}
