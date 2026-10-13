/**
 * Сценарий заявки целиком: добавление позиции, изменение количества,
 * проверка формы, отправка и обработка ответа сервера.
 *
 * Сеть подменяется на уровне общего API-клиента: проверяется в том
 * числе то, ЧТО именно уходит на backend.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@oinau/api-client';

import { ProductCard } from '@/components/catalog/ProductCard';
import { Providers } from '@/components/layout/Providers';
import { SiteHeader } from '@/components/layout/SiteHeader';
import { makeCategories, makeProduct, onRequestPrice } from './factories';

const fetchRegions = vi.fn();
const submitRequest = vi.fn();

vi.mock('@/lib/api/requests', () => ({
  fetchRegions: () => fetchRegions(),
  submitRequest: (...args: unknown[]) => submitRequest(...args),
  newIdempotencyKey: () => 'test-idempotency-key',
}));

function renderShop(product = makeProduct()) {
  return render(
    <Providers>
      <SiteHeader categories={makeCategories()} />
      <ProductCard product={product} />
    </Providers>,
  );
}

async function openDrawerWithItem(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Добавить в корзину' }));
  await user.click(screen.getByRole('button', { name: /^Корзина/ }));
  return screen.getByRole('dialog', { name: 'Корзина' });
}

beforeEach(() => {
  fetchRegions.mockResolvedValue([
    { id: 1, code: 'almaty', name: 'Алматы' },
    { id: 2, code: 'astana', name: 'Астана' },
  ]);
  submitRequest.mockReset();
});

describe('корзина', () => {
  it('пустая корзина предлагает каталог и быстрый заказ', async () => {
    const user = userEvent.setup();
    renderShop();

    await user.click(screen.getByRole('button', { name: 'Корзина' }));

    const dialog = screen.getByRole('dialog', { name: 'Корзина' });
    expect(within(dialog).getByText('В корзине пока пусто')).toBeInTheDocument();
  });

  it('добавление позиции обновляет счётчик в шапке', async () => {
    const user = userEvent.setup();
    renderShop();

    await user.click(screen.getByRole('button', { name: 'Добавить в корзину' }));

    expect(await screen.findByRole('button', { name: 'Корзина: 1' })).toBeInTheDocument();
  });

  it('состав сохраняется в localStorage и переживает перезагрузку', async () => {
    const user = userEvent.setup();
    const { unmount } = renderShop();

    await user.click(screen.getByRole('button', { name: 'Добавить в корзину' }));
    await waitFor(() =>
      expect(window.localStorage.getItem('oinau.request.v1')).toContain('RP-016'),
    );

    unmount();
    renderShop();

    expect(await screen.findByRole('button', { name: 'Корзина: 1' })).toBeInTheDocument();
  });

  it('повторное добавление не создаёт вторую позицию с тем же артикулом', async () => {
    const user = userEvent.setup();
    renderShop();

    await user.click(screen.getByRole('button', { name: 'Добавить в корзину' }));
    await user.click(await screen.findByRole('button', { name: /Добавлено|Добавить ещё/ }));

    expect(await screen.findByRole('button', { name: 'Корзина: 1' })).toBeInTheDocument();
  });

  it('количество меняется и позицию можно убрать', async () => {
    const user = userEvent.setup();
    renderShop();
    const dialog = await openDrawerWithItem(user);

    const quantity = within(dialog).getByRole('spinbutton', {
      name: /Количество: Канат армированный/,
    });
    expect(quantity).toHaveValue(1);

    await user.click(within(dialog).getByRole('button', { name: /Увеличить количество/ }));
    expect(quantity).toHaveValue(2);

    await user.click(within(dialog).getByRole('button', { name: /Убрать из корзины/ }));
    expect(within(dialog).getByText('В корзине пока пусто')).toBeInTheDocument();
  });

  it('позиция «по запросу» добавляется кнопкой запроса стоимости', async () => {
    const user = userEvent.setup();
    renderShop(makeProduct({ price: onRequestPrice, sku: 'SL-250', availability: 'ON_REQUEST' }));

    await user.click(screen.getByRole('button', { name: 'Запросить стоимость' }));

    expect(await screen.findByRole('button', { name: 'Корзина: 1' })).toBeInTheDocument();
  });
});

describe('форма заявки', () => {
  it('не отправляет форму без обязательных полей', async () => {
    const user = userEvent.setup();
    renderShop();
    const dialog = await openDrawerWithItem(user);

    await user.click(within(dialog).getByRole('button', { name: 'Отправить заявку' }));

    expect(await within(dialog).findByText('Укажите, как к вам обращаться')).toBeInTheDocument();
    expect(within(dialog).getByText('Укажите телефон для связи')).toBeInTheDocument();
    expect(submitRequest).not.toHaveBeenCalled();
  });

  it('проверяет длину номера телефона', async () => {
    const user = userEvent.setup();
    renderShop();
    const dialog = await openDrawerWithItem(user);

    await user.type(within(dialog).getByLabelText(/Имя/), 'Иван Петров');
    await user.type(within(dialog).getByLabelText(/Телефон/), '+7 70');
    await user.click(within(dialog).getByRole('button', { name: 'Отправить заявку' }));

    expect(
      await within(dialog).findByText('В номере должно быть от 5 до 15 цифр'),
    ).toBeInTheDocument();
    expect(submitRequest).not.toHaveBeenCalled();
  });

  it('проверяет адрес электронной почты', async () => {
    const user = userEvent.setup();
    renderShop();
    const dialog = await openDrawerWithItem(user);

    await user.type(within(dialog).getByLabelText(/Имя/), 'Иван');
    await user.type(within(dialog).getByLabelText(/Телефон/), '+77011234567');
    await user.type(within(dialog).getByLabelText(/Email/), 'не-почта');
    await user.click(within(dialog).getByRole('button', { name: 'Отправить заявку' }));

    expect(await within(dialog).findByText(/Проверьте адрес/)).toBeInTheDocument();
  });

  it('отправляет только артикулы и количества, показывает номер заявки', async () => {
    const user = userEvent.setup();
    submitRequest.mockResolvedValue({
      number: 'R-2026-000142',
      created_at: '2026-09-13T10:00:00Z',
      currency: 'KZT',
      total_estimate: '7000.00',
      items: [],
    });

    renderShop();
    const dialog = await openDrawerWithItem(user);

    await user.type(within(dialog).getByLabelText(/Имя/), 'Иван Петров');
    await user.type(within(dialog).getByLabelText(/Телефон/), '+7 701 123 45 67');
    await user.type(within(dialog).getByLabelText(/Комментарий/), 'Нужен к пятнице');
    await user.click(within(dialog).getByRole('button', { name: 'Отправить заявку' }));

    await waitFor(() => expect(submitRequest).toHaveBeenCalledTimes(1));
    const [payload, key] = submitRequest.mock.calls[0] as [Record<string, unknown>, string];

    expect(payload).toMatchObject({
      name: 'Иван Петров',
      phone: '+7 701 123 45 67',
      email: null,
      company: null,
      comment: 'Нужен к пятнице',
      items: [{ sku: 'RP-016', quantity: '1' }],
    });
    // Цена и название на сервер не уходят: их подставляет backend.
    expect(payload.items).toEqual([{ sku: 'RP-016', quantity: '1' }]);
    expect(key).toBe('test-idempotency-key');

    expect(await within(dialog).findByText('Заявка отправлена')).toBeInTheDocument();
    expect(within(dialog).getByText('№ R-2026-000142')).toBeInTheDocument();
    expect(window.localStorage.getItem('oinau.request.v1')).toBe('[]');
  });

  it('заявка без суммы объясняет, что цену посчитает менеджер', async () => {
    const user = userEvent.setup();
    submitRequest.mockResolvedValue({
      number: 'R-2026-000143',
      created_at: '2026-09-13T10:00:00Z',
      currency: 'KZT',
      total_estimate: null,
      items: [],
    });

    renderShop();
    const dialog = await openDrawerWithItem(user);
    await user.type(within(dialog).getByLabelText(/Имя/), 'Иван');
    await user.type(within(dialog).getByLabelText(/Телефон/), '+77011234567');
    await user.click(within(dialog).getByRole('button', { name: 'Отправить заявку' }));

    expect(await within(dialog).findByText(/сумму рассчитает менеджер/)).toBeInTheDocument();
  });
});

describe('ошибки отправки', () => {
  it('называет артикулы недоступных позиций', async () => {
    const user = userEvent.setup();
    submitRequest.mockRejectedValue(
      new ApiError(422, 'product_unavailable', 'Товар недоступен для заявки', {
        skus: ['RP-016'],
      }),
    );

    renderShop();
    const dialog = await openDrawerWithItem(user);
    await user.type(within(dialog).getByLabelText(/Имя/), 'Иван');
    await user.type(within(dialog).getByLabelText(/Телефон/), '+77011234567');
    await user.click(within(dialog).getByRole('button', { name: 'Отправить заявку' }));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('RP-016');
    // Состав не очищается: посетителю есть что исправить.
    expect(within(dialog).getByText('Канат армированный Ø16 мм')).toBeInTheDocument();
  });

  it('объясняет количество ниже минимальной партии', async () => {
    const user = userEvent.setup();
    submitRequest.mockRejectedValue(
      new ApiError(422, 'quantity_below_minimum', 'Количество меньше минимальной партии', {
        items: [{ sku: 'RP-016', quantity: '1', min_order_qty: '5' }],
      }),
    );

    renderShop();
    const dialog = await openDrawerWithItem(user);
    await user.type(within(dialog).getByLabelText(/Имя/), 'Иван');
    await user.type(within(dialog).getByLabelText(/Телефон/), '+77011234567');
    await user.click(within(dialog).getByRole('button', { name: 'Отправить заявку' }));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('минимум 5');
  });

  it('объясняет превышение частоты обращений', async () => {
    const user = userEvent.setup();
    submitRequest.mockRejectedValue(new ApiError(429, 'rate_limited', 'Слишком часто'));

    renderShop();
    const dialog = await openDrawerWithItem(user);
    await user.type(within(dialog).getByLabelText(/Имя/), 'Иван');
    await user.type(within(dialog).getByLabelText(/Телефон/), '+77011234567');
    await user.click(within(dialog).getByRole('button', { name: 'Отправить заявку' }));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Слишком много заявок');
  });

  it('регион не спрашивается: поля нет и справочник не запрашивается', async () => {
    const user = userEvent.setup();
    renderShop();
    const dialog = await openDrawerWithItem(user);

    expect(within(dialog).queryByLabelText(/Регион/)).not.toBeInTheDocument();
    expect(fetchRegions).not.toHaveBeenCalled();
  });
});

describe('доступность корзины', () => {
  it('панель — модальный диалог и закрывается по Esc', async () => {
    const user = userEvent.setup();
    renderShop();
    const dialog = await openDrawerWithItem(user);

    expect(dialog).toHaveAttribute('aria-modal', 'true');

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: 'Корзина' })).not.toBeInTheDocument();
  });
});
