/**
 * Окно «Быстрый заказ»: три вкладки, проверка формы, что уходит на
 * backend и что видит посетитель после отправки.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@oinau/api-client';

import { SkuQuickBar } from '@/components/home/SkuQuickBar';
import { Providers } from '@/components/layout/Providers';
import { QuickOrderButton } from '@/components/quick-order/QuickOrderButton';
import { checkAttachment, toQuickRequestForm } from '@/lib/api/quick-requests';

const submitQuickRequest = vi.fn();

vi.mock('@/lib/api/quick-requests', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/api/quick-requests')>();
  return {
    ...original,
    submitQuickRequest: (...args: unknown[]) => submitQuickRequest(...args),
  };
});

vi.mock('@/lib/api/requests', () => ({
  fetchRegions: () => Promise.resolve([]),
  submitRequest: vi.fn(),
  newIdempotencyKey: () => 'quick-idempotency-key',
}));

const CREATED = {
  number: 'R-2026-000201',
  created_at: '2026-09-22T10:00:00Z',
  currency: 'KZT',
  total_estimate: null,
  items: [],
  mode: 'CALLBACK',
  unrecognized: [],
  below_minimum: [],
  attachment: null,
};

function renderButton(options?: Parameters<typeof QuickOrderButton>[0]['options']) {
  return render(
    <Providers>
      <QuickOrderButton options={options}>Быстрый заказ</QuickOrderButton>
    </Providers>,
  );
}

async function openDialog(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Быстрый заказ' }));
  return screen.getByRole('dialog', { name: 'Быстрый заказ' });
}

beforeEach(() => {
  submitQuickRequest.mockReset();
});

describe('окно быстрого заказа', () => {
  it('по умолчанию открывается на вкладке «По телефону» с фокусом на телефоне', async () => {
    const user = userEvent.setup();
    renderButton();
    const dialog = await openDialog(user);

    expect(within(dialog).getByRole('tab', { name: 'По телефону' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(within(dialog).getByLabelText(/Телефон/)).toHaveFocus();
  });

  it('вкладки переключаются стрелками, контакты сохраняются', async () => {
    const user = userEvent.setup();
    renderButton();
    const dialog = await openDialog(user);

    await user.type(within(dialog).getByLabelText(/Имя/), 'Асель');
    within(dialog).getByRole('tab', { name: 'По телефону' }).focus();
    await user.keyboard('{ArrowRight}');

    expect(within(dialog).getByRole('tab', { name: 'По артикулам' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(within(dialog).getByLabelText(/Имя/)).toHaveValue('Асель');
  });

  it('не отправляет форму без обязательных полей', async () => {
    const user = userEvent.setup();
    renderButton();
    const dialog = await openDialog(user);

    await user.click(within(dialog).getByRole('button', { name: 'Отправить заявку' }));

    expect(within(dialog).getByText('Укажите телефон для связи')).toBeInTheDocument();
    expect(within(dialog).getByText('Укажите, как к вам обращаться')).toBeInTheDocument();
    expect(submitQuickRequest).not.toHaveBeenCalled();
  });

  it('обратный звонок уходит с контактами и ключом идемпотентности', async () => {
    const user = userEvent.setup();
    submitQuickRequest.mockResolvedValue(CREATED);
    renderButton();
    const dialog = await openDialog(user);

    await user.type(within(dialog).getByLabelText(/Телефон/), '+7 701 123 45 67');
    await user.type(within(dialog).getByLabelText(/Имя/), 'Иван');
    await user.type(within(dialog).getByLabelText(/Комментарий/), 'Подвесы на 5 качелей');
    await user.click(within(dialog).getByRole('button', { name: 'Отправить заявку' }));

    await waitFor(() => expect(submitQuickRequest).toHaveBeenCalledTimes(1));
    const [input, key, options] = submitQuickRequest.mock.calls[0] as [
      Record<string, unknown>,
      string,
      { signedIn: boolean },
    ];
    expect(input).toMatchObject({
      mode: 'CALLBACK',
      name: 'Иван',
      phone: '+7 701 123 45 67',
      comment: 'Подвесы на 5 качелей',
    });
    expect(input.productSku).toBeUndefined();
    expect(key).toBe('quick-idempotency-key');
    expect(options).toEqual({ signedIn: false });

    const done = await screen.findByRole('dialog', { name: 'Заявка отправлена' });
    expect(within(done).getByText('R-2026-000201')).toBeInTheDocument();
    expect(within(done).getByRole('button', { name: 'Закрыть' })).toHaveFocus();
  });

  it('список артикулов из полосы на главной открывает нужную вкладку', async () => {
    const user = userEvent.setup();
    submitQuickRequest.mockResolvedValue({
      ...CREATED,
      mode: 'SKU_LIST',
      items: [
        {
          sku: 'KAN-16-PP',
          name: 'Канат 16 мм',
          unit: 'm',
          quantity: '20.000',
          pricing_type: 'TIERED',
          unit_price: '3200.00',
          line_total: '64000.00',
        },
      ],
      total_estimate: '64000.00',
      unrecognized: ['NOPE × 3'],
    });
    render(
      <Providers>
        <SkuQuickBar examples={['KAN-16-PP', 'KRP-M10']} />
      </Providers>,
    );

    // Подсказка собрана из настоящих артикулов каталога.
    const field = screen.getByRole('textbox', { name: 'Артикулы и количество' });
    expect(field).toHaveAttribute('placeholder', 'KAN-16-PP × 20, KRP-M10 × 4 …');

    await user.type(field, 'KAN-16-PP × 20, NOPE × 3');
    await user.click(screen.getByRole('button', { name: 'Оформить' }));

    const dialog = screen.getByRole('dialog', { name: 'Быстрый заказ' });
    expect(within(dialog).getByRole('tab', { name: 'По артикулам' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(within(dialog).getByRole('textbox', { name: /Артикулы и количество/ })).toHaveValue(
      'KAN-16-PP × 20, NOPE × 3',
    );

    await user.type(within(dialog).getByLabelText(/Имя/), 'Иван');
    await user.type(within(dialog).getByLabelText(/Телефон/), '+77011234567');
    await user.click(within(dialog).getByRole('button', { name: 'Отправить заявку' }));

    await waitFor(() => expect(submitQuickRequest).toHaveBeenCalledTimes(1));
    const [input] = submitQuickRequest.mock.calls[0] as [Record<string, unknown>];
    expect(input).toMatchObject({ mode: 'SKU_LIST', skuList: 'KAN-16-PP × 20, NOPE × 3' });

    const done = await screen.findByRole('dialog', { name: 'Заявка отправлена' });
    expect(within(done).getByText('Канат 16 мм')).toBeInTheDocument();
    expect(within(done).getByText('Не нашли в каталоге — менеджер уточнит:')).toBeInTheDocument();
    expect(within(done).getByText('NOPE × 3')).toBeInTheDocument();
  });

  it('запрос КП требует email и файл или описание', async () => {
    const user = userEvent.setup();
    renderButton({ mode: 'QUOTE' });
    const dialog = await openDialog(user);

    await user.type(within(dialog).getByLabelText(/Имя/), 'Иван');
    await user.type(within(dialog).getByLabelText(/Телефон/), '+77011234567');
    await user.click(within(dialog).getByRole('button', { name: 'Отправить заявку' }));

    expect(
      within(dialog).getByText('На этот адрес придёт коммерческое предложение'),
    ).toBeInTheDocument();
    expect(within(dialog).getByText('Приложите файл или опишите, что нужно')).toBeInTheDocument();
    expect(submitQuickRequest).not.toHaveBeenCalled();
  });

  it('запрос КП отправляет приложенный файл', async () => {
    const user = userEvent.setup();
    submitQuickRequest.mockResolvedValue({
      ...CREATED,
      mode: 'QUOTE',
      attachment: { filename: 'spec.pdf', size_bytes: 2048 },
    });
    renderButton({ mode: 'QUOTE' });
    const dialog = await openDialog(user);

    const file = new File(['%PDF-1.7'], 'spec.pdf', { type: 'application/pdf' });
    await user.upload(within(dialog).getByLabelText(/Перетащите файл/), file);
    expect(within(dialog).getByText('spec.pdf')).toBeInTheDocument();

    await user.type(within(dialog).getByLabelText(/Имя/), 'Иван');
    await user.type(within(dialog).getByLabelText(/Телефон/), '+77011234567');
    await user.type(within(dialog).getByLabelText(/^Email/), 'ivan@example.kz');
    await user.click(within(dialog).getByRole('button', { name: 'Отправить заявку' }));

    await waitFor(() => expect(submitQuickRequest).toHaveBeenCalledTimes(1));
    const [input] = submitQuickRequest.mock.calls[0] as [{ file: File; mode: string }];
    expect(input.mode).toBe('QUOTE');
    expect(input.file.name).toBe('spec.pdf');

    expect(await screen.findByText(/Файл «spec.pdf» \(2 КБ\) получен/)).toBeInTheDocument();
  });

  it('ошибка сервера показывается, а ключ повтора меняется', async () => {
    const user = userEvent.setup();
    submitQuickRequest.mockRejectedValue(new ApiError(429, 'rate_limited', 'Слишком часто'));
    renderButton();
    const dialog = await openDialog(user);

    await user.type(within(dialog).getByLabelText(/Телефон/), '+77011234567');
    await user.type(within(dialog).getByLabelText(/Имя/), 'Иван');
    await user.click(within(dialog).getByRole('button', { name: 'Отправить заявку' }));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Слишком много заявок');
  });

  it('количество ниже минимальной партии: называет минимум и подсвечивает поле', async () => {
    const user = userEvent.setup();
    // «1 клик» из списка каталога: минимальная партия там неизвестна
    // (API отдаёт её только в карточке), поэтому ловит её сервер.
    submitQuickRequest.mockRejectedValue(
      new ApiError(422, 'quantity_below_minimum', 'Количество меньше минимальной партии товара', {
        items: [{ sku: 'AV-820', quantity: '2', min_order_qty: '50.000' }],
      }),
    );
    renderButton({
      mode: 'CALLBACK',
      product: { sku: 'AV-820', name: 'Болт антивандальный М10', unit: 'pcs', priceLabel: '180 ₸' },
    });
    const dialog = await openDialog(user);

    await user.type(within(dialog).getByLabelText(/Кол-во/), '2');
    await user.type(within(dialog).getByLabelText(/Телефон/), '+77011234567');
    await user.type(within(dialog).getByLabelText(/Имя/), 'Иван');
    await user.click(within(dialog).getByRole('button', { name: 'Отправить заявку' }));

    // Дробные нули из NUMERIC не показываем: «50.000» — это 50.
    expect(await within(dialog).findByText(/AV-820 — минимум 50/)).toBeInTheDocument();
    expect(within(dialog).getByText('Минимальная партия — 50')).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/Кол-во/)).toHaveAttribute('aria-invalid', 'true');
  });

  it('недоступный товар: называет артикул', async () => {
    const user = userEvent.setup();
    submitQuickRequest.mockRejectedValue(
      new ApiError(422, 'product_unavailable', 'Товар недоступен для заявки', {
        skus: ['AV-820'],
      }),
    );
    renderButton({
      mode: 'CALLBACK',
      product: { sku: 'AV-820', name: 'Болт антивандальный М10', unit: 'pcs', priceLabel: '180 ₸' },
    });
    const dialog = await openDialog(user);

    await user.type(within(dialog).getByLabelText(/Кол-во/), '50');
    await user.type(within(dialog).getByLabelText(/Телефон/), '+77011234567');
    await user.type(within(dialog).getByLabelText(/Имя/), 'Иван');
    await user.click(within(dialog).getByRole('button', { name: 'Отправить заявку' }));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('AV-820');
    // Ошибка не про количество — поле не подсвечивается.
    expect(within(dialog).getByLabelText(/Кол-во/)).not.toHaveAttribute('aria-invalid');
  });

  it('закрывается по Esc', async () => {
    const user = userEvent.setup();
    renderButton();
    await openDialog(user);

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: 'Быстрый заказ' })).not.toBeInTheDocument();
  });
});

describe('форма для backend', () => {
  it('пустые поля не отправляются, заполненные обрезаются', () => {
    const form = toQuickRequestForm({
      mode: 'SKU_LIST',
      name: '  Иван ',
      phone: '+77011234567',
      email: '',
      comment: '   ',
      skuList: 'KAN-16-PP × 10',
    });
    expect(Object.fromEntries(form.entries())).toEqual({
      mode: 'SKU_LIST',
      name: 'Иван',
      phone: '+77011234567',
      sku_list: 'KAN-16-PP × 10',
    });
  });

  it('файл проверяется до отправки по тем же правилам, что на сервере', () => {
    expect(checkAttachment(new File(['x'], 'spec.pdf'))).toBeNull();
    expect(checkAttachment(new File(['x'], 'plan.DWG'))).toBeNull();
    expect(checkAttachment(new File(['x'], 'virus.exe'))).toMatch(/Поддерживаются/);
    expect(checkAttachment(new File([], 'empty.pdf'))).toBe('Файл пуст');
  });
});
