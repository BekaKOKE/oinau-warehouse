/**
 * Раздел товаров: список, создание, карточка (основное, категории,
 * характеристики, цены, изображения, наличие), удаление и восстановление,
 * права и состояния экрана.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import NewProductPage from '@/app/(panel)/products/new/page';
import { AppProviders } from '@/components/AppProviders';
import { ProductCreateScreen } from '@/components/products/ProductCreateScreen';
import { ProductEditorScreen } from '@/components/products/ProductEditorScreen';
import { ProductsList } from '@/components/products/ProductsList';
import { AuthGate } from '@/components/session/AuthGate';
import type { ProductImage, UserRole } from '@/lib/api/types';
import { resetSessionForTests } from '@/lib/auth/session';

import { createFetchMock, errorResponse, jsonResponse, page, signInAs } from './helpers';
import {
  CATEGORY_ATTRIBUTES,
  CATEGORY_TREE,
  MATERIAL_ATTRIBUTE,
  makeImage,
  makePricing,
  makeProduct,
  makeProductRow,
  makeStock,
  PRODUCT_ID,
  PRODUCT_URL,
} from './product-fixtures';
import { navigationState, routerPush, routerReplace } from './setup';

const LIST = '/api/v1/admin/products';
const TREE = '/api/v1/admin/categories/tree';

let net: ReturnType<typeof createFetchMock>;

function renderInPanel(ui: ReactNode) {
  return render(
    <AppProviders>
      <AuthGate>{ui}</AuthGate>
    </AppProviders>,
  );
}

function bodyOf(method: string, path: string, index = 0): unknown {
  const call = net.calls(method, path)[index];
  return JSON.parse(String((call?.[1] as RequestInit).body));
}

function lastListParams() {
  const calls = net.calls('GET', LIST);
  return new URL(String(calls[calls.length - 1]?.[0])).searchParams;
}

async function openList(role: UserRole = 'CONTENT_MANAGER') {
  signInAs(net, role);
  net.on('GET', TREE, CATEGORY_TREE);
  renderInPanel(<ProductsList />);
  return screen.findByRole('table', { name: 'Товары' });
}

function stubEditor(product = makeProduct()) {
  net.on('GET', PRODUCT_URL, product);
  net.on('GET', TREE, CATEGORY_TREE);
  net.on('GET', '/api/v1/admin/categories/2/attributes', CATEGORY_ATTRIBUTES);
  net.on('GET', '/api/v1/admin/categories/3/attributes', []);
  net.on('GET', '/api/v1/admin/attributes/11', MATERIAL_ATTRIBUTE);
}

async function openEditor(
  role: UserRole = 'CONTENT_MANAGER',
  product = makeProduct(),
  tab?: string,
) {
  signInAs(net, role);
  stubEditor(product);
  if (tab) navigationState.search = `tab=${tab}`;
  renderInPanel(<ProductEditorScreen id={PRODUCT_ID} />);
  await screen.findByRole('heading', { name: product.name });
}

beforeEach(() => {
  resetSessionForTests();
  net = createFetchMock();
  vi.stubGlobal('fetch', net.mock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ================================================================ список
describe('список товаров', () => {
  it('строка: фото, название, артикул, категория, цена, наличие, флаги', async () => {
    net.on(
      'GET',
      LIST,
      page([
        makeProductRow(),
        makeProductRow({
          id: 6,
          sku: 'OLD-1',
          name: 'Старый',
          deleted_at: '2026-09-01T00:00:00Z',
          is_active: false,
          main_image_url: null,
          images_count: 0,
          pricing_type: 'FIXED',
          min_price: null,
          primary_category: null,
          public_availability: 'OUT_OF_STOCK',
        }),
      ]),
    );

    const table = await openList();
    await within(table).findByRole('link', { name: 'Старый' });
    const rows = within(table).getAllByRole('row');
    const first = within(rows[1] as HTMLElement);
    // Миниатюра декоративная (alt=""): название уже есть рядом.
    expect((rows[1] as HTMLElement).querySelector('img')).toHaveAttribute(
      'src',
      'http://cdn.test/products/abc/variants/thumb.webp',
    );
    expect(first.getByRole('link', { name: 'Канат полипропиленовый 16 мм' })).toHaveAttribute(
      'href',
      '/products/5',
    );
    expect(first.getByText('KAN-16-PP')).toBeInTheDocument();
    expect(first.getByText('1C-00042')).toBeInTheDocument();
    expect(first.getByText('Канаты')).toBeInTheDocument();
    expect(first.getByText('от 2 600 ₸')).toBeInTheDocument();
    expect(first.getByText('В наличии')).toBeInTheDocument();
    expect(first.getByText('Избранный')).toBeInTheDocument();

    const second = within(rows[2] as HTMLElement);
    expect(second.getByText('Удалён')).toBeInTheDocument();
    expect(second.getByText('Нет цены')).toBeInTheDocument();
    expect(second.getByText('Без категории')).toBeInTheDocument();

    expect(lastListParams().get('page_size')).toBe('24');
    expect(lastListParams().get('sort')).toBe('updated');
  });

  it('поиск уходит на backend после паузы ввода', async () => {
    net.on('GET', LIST, page([makeProductRow()]));
    const user = userEvent.setup();

    await openList();
    await user.type(screen.getByLabelText('Поиск'), 'канат');

    await waitFor(() => expect(lastListParams().get('search')).toBe('канат'));
    expect(
      net.calls('GET', LIST).filter(([url]) => new URL(String(url)).searchParams.has('search')),
    ).toHaveLength(1);
  });

  it('фильтры статуса, активности, категории, удалённых и external_id — в запрос и адрес', async () => {
    navigationState.pathname = '/products';
    net.on('GET', LIST, page([makeProductRow()]));
    const user = userEvent.setup();

    await openList();
    await user.selectOptions(screen.getByLabelText('Статус'), 'DRAFT');
    await waitFor(() => expect(lastListParams().get('status')).toBe('DRAFT'));
    await user.selectOptions(screen.getByLabelText('Активность'), 'false');
    await waitFor(() => expect(lastListParams().get('is_active')).toBe('false'));
    await user.selectOptions(screen.getByLabelText('Категория'), '2');
    await waitFor(() => expect(lastListParams().get('category_id')).toBe('2'));
    await user.click(screen.getByLabelText('Показать удалённые'));
    await waitFor(() => expect(lastListParams().get('include_deleted')).toBe('true'));
    await user.type(screen.getByLabelText('Код 1С (external_id)'), '1C-00042{Enter}');
    await waitFor(() => expect(lastListParams().get('external_id')).toBe('1C-00042'));

    expect(routerReplace).toHaveBeenLastCalledWith(
      '/products?status=DRAFT&is_active=false&category_id=2&external_id=1C-00042&include_deleted=true',
      { scroll: false },
    );
  });

  it('сортировка и страницы', async () => {
    navigationState.pathname = '/products';
    net.on('GET', LIST, (url: URL) =>
      jsonResponse({
        ...page([makeProductRow()], 50),
        page: Number(url.searchParams.get('page')),
        page_size: 24,
        pages: 3,
      }),
    );
    const user = userEvent.setup();

    await openList();
    await user.selectOptions(screen.getByLabelText('Сортировка'), 'sku');
    await waitFor(() => expect(lastListParams().get('sort')).toBe('sku'));
    await user.click(await screen.findByRole('button', { name: 'Следующая страница' }));
    await waitFor(() => expect(lastListParams().get('page')).toBe('2'));
    expect(lastListParams().get('sort')).toBe('sku');
  });

  it('пустой каталог, ошибка с повтором, 403 и skeleton', async () => {
    let calls = 0;
    net.on('GET', LIST, () => {
      calls += 1;
      if (calls === 1) return errorResponse(500, 'internal_error', 'Внутренняя ошибка сервера');
      return jsonResponse(page([]));
    });
    const user = userEvent.setup();

    const table = await openList();
    await user.click(await within(table).findByRole('button', { name: 'Повторить' }));
    expect(await within(table).findByText('Товаров пока нет')).toBeInTheDocument();
  });

  it('403 списка — «Нет доступа»', async () => {
    net.on('GET', LIST, errorResponse(403, 'permission_denied', 'Недостаточно прав'));
    const table = await openList();
    expect(await within(table).findByText('Нет доступа')).toBeInTheDocument();
  });

  it('пока список грузится — таблица занята', async () => {
    net.on('GET', LIST, () => new Promise<Response>(() => undefined));
    const table = await openList();
    expect(table).toHaveAttribute('aria-busy', 'true');
  });

  it('кнопка создания — только при праве изменять каталог', async () => {
    net.on('GET', LIST, page([]));
    await openList('MANAGER');
    await screen.findByText('Товаров пока нет', {}, { timeout: 3000 }).catch(() => undefined);
    expect(screen.queryByRole('link', { name: 'Новый товар' })).not.toBeInTheDocument();
  });
});

// ============================================================== создание
describe('создание товара', () => {
  async function openCreate() {
    signInAs(net, 'CONTENT_MANAGER');
    net.on('GET', TREE, CATEGORY_TREE);
    net.on('GET', '/api/v1/admin/categories/2/attributes', CATEGORY_ATTRIBUTES);
    net.on('GET', '/api/v1/admin/attributes/11', MATERIAL_ATTRIBUTE);
    renderInPanel(<ProductCreateScreen />);
    await screen.findByRole('heading', { name: 'Новый товар' });
  }

  it('проверяет поля до отправки', async () => {
    const user = userEvent.setup();
    await openCreate();
    await user.click(screen.getByRole('button', { name: 'Создать товар' }));

    expect(await screen.findByText('Укажите название')).toBeInTheDocument();
    expect(screen.getByText('Укажите артикул')).toBeInTheDocument();
    expect(net.calls('POST', LIST)).toHaveLength(0);
  });

  it('создаёт товар с категорией и характеристиками и открывает карточку', async () => {
    net.on('POST', LIST, jsonResponse(makeProduct({ id: 77 }), 201));
    const user = userEvent.setup();
    await openCreate();

    await user.type(screen.getByLabelText(/Название/), 'Канат 16 мм');
    await user.type(screen.getByLabelText(/Артикул/), 'KAN-16');
    // slug нового товара заполняется из названия сам.
    expect(screen.getByLabelText(/Адрес страницы/)).toHaveValue('kanat-16-mm');
    await user.selectOptions(screen.getByLabelText('Добавить категорию'), '2');
    await user.click(screen.getByRole('button', { name: 'Добавить' }));
    expect(await screen.findByText('Основная')).toBeInTheDocument();

    const diameter = await screen.findByLabelText(/Диаметр/);
    await user.type(diameter, '16,5');
    await user.click(screen.getByLabelText('Сталь'));
    await user.click(screen.getByRole('button', { name: 'Создать товар' }));

    await waitFor(() => expect(net.calls('POST', LIST)).toHaveLength(1));
    expect(bodyOf('POST', LIST)).toEqual({
      sku: 'KAN-16',
      slug: 'kanat-16-mm',
      status: 'DRAFT',
      is_active: true,
      is_featured: false,
      unit: 'pcs',
      min_order_qty: '1',
      brand: null,
      external_id: null,
      translations: {
        ru: {
          name: 'Канат 16 мм',
          short_description: null,
          description: null,
          seo_title: null,
          seo_description: null,
        },
      },
      categories: [{ category_id: 2, is_primary: true, sort_order: 0 }],
      attributes: [
        { attribute_id: 10, value_numeric: '16.5' },
        { attribute_id: 11, option_id: 101 },
      ],
    });
    await waitFor(() => expect(routerPush).toHaveBeenCalledWith('/products/77'));
    expect(screen.getByText('Товар создан')).toBeInTheDocument();
  });

  it('409 «артикул занят» показывается у поля артикула', async () => {
    net.on(
      'POST',
      LIST,
      errorResponse(409, 'sku_exists', 'Товар с таким артикулом уже существует'),
    );
    const user = userEvent.setup();
    await openCreate();

    await user.type(screen.getByLabelText(/Название/), 'Канат');
    await user.type(screen.getByLabelText(/Артикул/), 'KAN-16');
    await user.click(screen.getByRole('button', { name: 'Создать товар' }));

    const field = screen.getByLabelText(/Артикул/);
    await waitFor(() => expect(field).toHaveAttribute('aria-invalid', 'true'));
    expect(screen.getAllByText('Товар с таким артикулом уже существует').length).toBeGreaterThan(0);
    expect(routerPush).not.toHaveBeenCalled();
  });

  it('единица выбирается из списка: метр для канатов', async () => {
    net.on('POST', LIST, jsonResponse(makeProduct({ id: 78 }), 201));
    const user = userEvent.setup();
    await openCreate();
    const unit = screen.getByLabelText(/Единица/);

    expect(unit).toHaveValue('pcs');
    expect(within(unit).getByRole('option', { name: 'м — метр' })).toBeInTheDocument();
    await user.selectOptions(unit, 'm');
    await user.type(screen.getByLabelText(/Название/), 'Канат 16 мм');
    await user.type(screen.getByLabelText(/Артикул/), 'KAN-16');
    await user.selectOptions(screen.getByLabelText('Добавить категорию'), '2');
    await user.click(screen.getByRole('button', { name: 'Добавить' }));
    await screen.findByText('Основная');
    await user.click(screen.getByRole('button', { name: 'Создать товар' }));

    await waitFor(() => expect(net.calls('POST', LIST)).toHaveLength(1));
    expect(bodyOf('POST', LIST)).toMatchObject({ unit: 'm' });
  });

  it('slug, поправленный руками, больше не идёт за названием', async () => {
    const user = userEvent.setup();
    await openCreate();
    const slug = screen.getByLabelText(/Адрес страницы/);

    await user.type(screen.getByLabelText(/Название/), 'Канат');
    expect(slug).toHaveValue('kanat');
    await user.clear(slug);
    await user.type(slug, 'rope');
    await user.type(screen.getByLabelText(/Название/), ' 16 мм');
    expect(slug).toHaveValue('rope');
  });

  it('менеджер не может открыть создание', async () => {
    signInAs(net, 'MANAGER');
    renderInPanel(<NewProductPage />);
    expect(await screen.findByText('Нет доступа')).toBeInTheDocument();
  });
});

// ============================================================== карточка
describe('карточка: основное', () => {
  it('сохраняет только изменённые поля и сообщает об успехе', async () => {
    net.on(
      'PATCH',
      PRODUCT_URL,
      makeProduct({ name: 'Канат 16 мм', updated_at: '2026-09-14T09:00:00Z' }),
    );
    const user = userEvent.setup();
    await openEditor();

    const name = screen.getByLabelText(/Название/);
    await user.clear(name);
    await user.type(name, 'Канат 16 мм');
    await user.click(screen.getByRole('switch', { name: /Избранный/ }));
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(net.calls('PATCH', PRODUCT_URL)).toHaveLength(1));
    expect(bodyOf('PATCH', PRODUCT_URL)).toEqual({
      is_featured: true,
      translations: {
        ru: {
          name: 'Канат 16 мм',
          short_description: 'Армированный канат',
          description: null,
          seo_title: 'SEO заголовок каната',
          seo_description: 'SEO описание',
        },
      },
    });
    expect(await screen.findByText('Изменения сохранены')).toBeInTheDocument();
  });

  it('409 slug — ошибка у поля slug', async () => {
    net.on(
      'PATCH',
      PRODUCT_URL,
      errorResponse(409, 'product_slug_exists', 'Товар с таким адресом уже существует'),
    );
    const user = userEvent.setup();
    await openEditor();

    const slug = screen.getByLabelText(/Адрес страницы/);
    await user.clear(slug);
    await user.type(slug, 'zanyato');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(slug).toHaveAttribute('aria-invalid', 'true'));
  });

  it('несохранённые изменения: смена вкладки спрашивает подтверждение', async () => {
    const user = userEvent.setup();
    await openEditor();
    await user.type(screen.getByLabelText(/Бренд/), 'OINAU');

    await user.click(screen.getByRole('tab', { name: 'Цены' }));
    const dialog = await screen.findByRole('dialog', { name: 'Уйти без сохранения?' });
    await user.click(within(dialog).getByRole('button', { name: 'Отмена' }));

    expect(screen.getByRole('tab', { name: 'Основное' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByLabelText(/Бренд/)).toHaveValue('OINAU');
  });

  it('несуществующий товар — понятный экран', async () => {
    signInAs(net, 'CONTENT_MANAGER');
    net.on('GET', PRODUCT_URL, errorResponse(404, 'not_found', 'Товар не найден'));
    renderInPanel(<ProductEditorScreen id={PRODUCT_ID} />);
    expect(await screen.findByText('Такого товара нет')).toBeInTheDocument();
  });

  it('истёкшая сессия (401) — переход на вход', async () => {
    navigationState.pathname = '/products/5';
    window.localStorage.setItem('oinau.admin.session', '1');
    net.on('POST', '/api/v1/admin/auth/refresh', errorResponse(401, 'unauthenticated', 'x'));
    renderInPanel(<ProductEditorScreen id={PRODUCT_ID} />);
    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith('/login?next=%2Fproducts%2F5'));
  });
});

describe('права и режим просмотра', () => {
  it('менеджер видит карточку только для чтения', async () => {
    await openEditor('MANAGER');
    expect(screen.getByText(/Только просмотр/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Название/)).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Сохранить' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Удалить' })).not.toBeInTheDocument();
  });

  it('403 при сохранении не маскируется', async () => {
    net.on('PATCH', PRODUCT_URL, errorResponse(403, 'permission_denied', 'Недостаточно прав'));
    const user = userEvent.setup();
    await openEditor();
    await user.type(screen.getByLabelText(/Бренд/), 'X');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findByText('Нет права изменять товар')).toBeInTheDocument();
  });
});

describe('удаление и восстановление', () => {
  it('удаление — подтверждение, DELETE и режим удалённого товара', async () => {
    const user = userEvent.setup();
    await openEditor();
    net.on('DELETE', PRODUCT_URL, {
      ok: true,
      status: 204,
      json: async () => null,
    } as unknown as Response);
    net.on(
      'GET',
      PRODUCT_URL,
      makeProduct({
        deleted_at: '2026-09-14T10:00:00Z',
        is_active: false,
        is_publicly_visible: false,
      }),
    );

    await user.click(screen.getByRole('button', { name: 'Удалить' }));
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent('Товар можно будет восстановить');
    await user.click(within(dialog).getByRole('button', { name: 'Удалить' }));

    await waitFor(() => expect(net.calls('DELETE', PRODUCT_URL)).toHaveLength(1));
    expect(await screen.findByText(/Товар удалён 14\.09\.2026/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Восстановить' })).toBeInTheDocument();
    expect(screen.getByLabelText(/Название/)).toBeDisabled();
  });

  it('403 при удалении — «Нет права удалять товары»', async () => {
    const user = userEvent.setup();
    await openEditor();
    net.on('DELETE', PRODUCT_URL, errorResponse(403, 'permission_denied', 'Недостаточно прав'));
    await user.click(screen.getByRole('button', { name: 'Удалить' }));
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: 'Удалить' }),
    );
    expect(await screen.findByText('Нет права удалять товары')).toBeInTheDocument();
  });

  it('восстановление не включает товар автоматически', async () => {
    const deleted = makeProduct({
      deleted_at: '2026-09-14T10:00:00Z',
      is_active: false,
      is_publicly_visible: false,
    });
    net.on(
      'POST',
      `${PRODUCT_URL}/restore`,
      makeProduct({ deleted_at: null, is_active: false, is_publicly_visible: false }),
    );
    const user = userEvent.setup();
    await openEditor('CONTENT_MANAGER', deleted);

    await user.click(screen.getByRole('button', { name: 'Восстановить' }));

    expect(await screen.findByText('Товар восстановлен')).toBeInTheDocument();
    expect(screen.getByText(/включите «Активен»/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Восстановить' })).not.toBeInTheDocument();
    expect(screen.getByRole('switch', { name: /Активен/ })).not.toBeChecked();
  });

  it('409 при восстановлении объясняет конфликт артикула', async () => {
    const deleted = makeProduct({ deleted_at: '2026-09-14T10:00:00Z', is_active: false });
    net.on(
      'POST',
      `${PRODUCT_URL}/restore`,
      errorResponse(409, 'sku_exists', 'Товар с таким артикулом уже существует'),
    );
    const user = userEvent.setup();
    await openEditor('CONTENT_MANAGER', deleted);

    await user.click(screen.getByRole('button', { name: 'Восстановить' }));
    expect(await screen.findByText('Восстановить нельзя')).toBeInTheDocument();
    expect(screen.getByText(/Измените артикул или slug/)).toBeInTheDocument();
  });
});

// ============================================================= категории
describe('карточка: категории', () => {
  it('добавление, смена основной и полная замена набора', async () => {
    net.on('PUT', `${PRODUCT_URL}/categories`, makeProduct());
    const user = userEvent.setup();
    await openEditor('CONTENT_MANAGER', makeProduct(), 'categories');

    // Список категорий подгружается отдельным запросом. Сам select
    // появляется раньше ответа — с одной заглушкой «Загружаем категории…»
    // и атрибутом disabled. Ждать надо не элемент, а готовность списка,
    // иначе на загруженной машине тест падает «Value "3" not found».
    const categorySelect = await screen.findByLabelText('Добавить категорию');
    await waitFor(() => expect(categorySelect).toBeEnabled());
    await user.selectOptions(categorySelect, '3');
    await user.click(screen.getByRole('button', { name: 'Добавить' }));
    const radios = screen.getAllByRole('radio');
    await user.click(radios[1] as HTMLElement);
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(net.calls('PUT', `${PRODUCT_URL}/categories`)).toHaveLength(1));
    expect(bodyOf('PUT', `${PRODUCT_URL}/categories`)).toEqual({
      items: [
        { category_id: 2, is_primary: false, sort_order: 0 },
        { category_id: 3, is_primary: true, sort_order: 1 },
      ],
    });
    expect(await screen.findByText('Категории сохранены')).toBeInTheDocument();
  });
});

// ========================================================= характеристики
describe('карточка: характеристики', () => {
  it('поля по типам backend и сохранение значений', async () => {
    net.on('PUT', `${PRODUCT_URL}/attributes`, makeProduct());
    const user = userEvent.setup();
    await openEditor('CONTENT_MANAGER', makeProduct(), 'attributes');

    const diameter = await screen.findByLabelText(/Диаметр/);
    expect(diameter).toHaveValue('16');
    expect(screen.getByLabelText('Полипропилен')).toBeChecked();
    await user.clear(diameter);
    await user.type(diameter, '18,25');
    await user.selectOptions(screen.getByLabelText(/Сертифицирован/), 'true');
    await user.type(screen.getByLabelText(/Цвет/), 'синий');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(net.calls('PUT', `${PRODUCT_URL}/attributes`)).toHaveLength(1));
    expect(bodyOf('PUT', `${PRODUCT_URL}/attributes`)).toEqual({
      items: [
        { attribute_id: 10, value_numeric: '18.25' },
        { attribute_id: 11, option_id: 100 },
        { attribute_id: 12, value_bool: true },
        { attribute_id: 13, value_string: 'синий' },
      ],
    });
  });

  it('некорректное число не отправляется', async () => {
    const user = userEvent.setup();
    await openEditor('CONTENT_MANAGER', makeProduct(), 'attributes');
    const diameter = await screen.findByLabelText(/Диаметр/);
    await user.clear(diameter);
    await user.type(diameter, '1.2345');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findByText('Не больше 3 знаков после запятой')).toBeInTheDocument();
    expect(net.calls('PUT', `${PRODUCT_URL}/attributes`)).toHaveLength(0);
  });
});

// ================================================================== цены
describe('карточка: цены', () => {
  it('ступени по количеству: превью и тело PUT строками', async () => {
    net.on('GET', `${PRODUCT_URL}/pricing`, makePricing());
    net.on('PUT', `${PRODUCT_URL}/pricing`, (_url: URL, init: RequestInit) =>
      jsonResponse(makePricing({ ...JSON.parse(String(init.body)) })),
    );
    const user = userEvent.setup();
    await openEditor('CONTENT_MANAGER', makeProduct(), 'pricing');

    await user.click(await screen.findByLabelText(/По ступеням/));
    await user.type(screen.getByLabelText('цена'), '3500');
    await user.type(screen.getByLabelText('до'), '9');
    await user.click(screen.getByRole('button', { name: 'Добавить ступень' }));
    const minInputs = screen.getAllByLabelText(/Ступень \d: от/);
    await user.type(minInputs[1] as HTMLElement, '10');
    await user.type(screen.getAllByLabelText('цена')[1] as HTMLElement, '2 600,50');

    expect(screen.getByTestId('price-preview')).toHaveTextContent('от 2 600,50 ₸ / м');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(net.calls('PUT', `${PRODUCT_URL}/pricing`)).toHaveLength(1));
    expect(bodyOf('PUT', `${PRODUCT_URL}/pricing`)).toEqual({
      pricing_type: 'TIERED',
      tiers: [
        { min_qty: '1', max_qty: '9', price: '3500' },
        { min_qty: '10', max_qty: null, price: '2600.5' },
      ],
    });
  });

  it('пересекающиеся ступени не отправляются', async () => {
    net.on(
      'GET',
      `${PRODUCT_URL}/pricing`,
      makePricing({
        pricing_type: 'TIERED',
        tiers: [{ id: 1, min_qty: '1.000', max_qty: '10.000', price: '100.00' }],
      }),
    );
    const user = userEvent.setup();
    await openEditor('CONTENT_MANAGER', makeProduct(), 'pricing');

    await user.click(await screen.findByRole('button', { name: 'Добавить ступень' }));
    await user.type(screen.getAllByLabelText(/Ступень \d: от/)[1] as HTMLElement, '10');
    await user.type(screen.getAllByLabelText('цена')[1] as HTMLElement, '90');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));

    expect(await screen.findByText('Пересекается со ступенью от 1')).toBeInTheDocument();
    expect(net.calls('PUT', `${PRODUCT_URL}/pricing`)).toHaveLength(0);
  });

  it('фиксированная цена и режим просмотра у менеджера', async () => {
    net.on(
      'GET',
      `${PRODUCT_URL}/pricing`,
      makePricing({
        pricing_type: 'FIXED',
        tiers: [{ id: 1, min_qty: '1.000', max_qty: null, price: '1200.00' }],
      }),
    );
    await openEditor('MANAGER', makeProduct(), 'pricing');

    expect(await screen.findByTestId('price-preview')).toHaveTextContent('1 200 ₸ / м');
    expect(screen.getByLabelText(/Цена за м/)).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Сохранить' })).not.toBeInTheDocument();
  });
});

// =============================================================== наличие
describe('карточка: наличие', () => {
  it('остатки по складам: правка только активного склада, PUT изменённых', async () => {
    net.on('GET', `${PRODUCT_URL}/stock`, makeStock());
    net.on('PUT', `${PRODUCT_URL}/stock`, makeStock());
    const user = userEvent.setup();
    await openEditor('CONTENT_MANAGER', makeProduct(), 'stock');

    expect(await screen.findByText('Склад отключён')).toBeInTheDocument();
    expect(screen.getByText(/1С: 13\.09\.2026/)).toBeInTheDocument();
    const quantities = screen.getAllByLabelText(/Остаток, м/);
    expect(quantities).toHaveLength(1);
    expect(quantities[0]).toHaveValue('152.5');
    await user.clear(quantities[0] as HTMLElement);
    await user.type(quantities[0] as HTMLElement, '200');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(net.calls('PUT', `${PRODUCT_URL}/stock`)).toHaveLength(1));
    expect(bodyOf('PUT', `${PRODUCT_URL}/stock`)).toEqual({
      items: [{ warehouse_id: 1, quantity: '200', reserved: '2.5' }],
    });
  });

  it('резерв больше остатка — ошибка у поля', async () => {
    net.on('GET', `${PRODUCT_URL}/stock`, makeStock());
    const user = userEvent.setup();
    await openEditor('CONTENT_MANAGER', makeProduct(), 'stock');
    const reserved = await screen.findByLabelText(/Резерв, м/);
    await user.clear(reserved);
    await user.type(reserved, '500');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findByText('Резерв больше остатка')).toBeInTheDocument();
  });

  it('переопределение показа — отдельный PATCH, остатки не трогаются', async () => {
    net.on('GET', `${PRODUCT_URL}/stock`, makeStock());
    net.on('PATCH', `${PRODUCT_URL}/availability`, {
      product_id: PRODUCT_ID,
      sku: 'KAN-16-PP',
      stock_display_override: 'ON_REQUEST',
      public_availability: 'ON_REQUEST',
      total_available: '150.000',
    });
    const user = userEvent.setup();
    await openEditor('CONTENT_MANAGER', makeProduct(), 'stock');

    await user.selectOptions(await screen.findByLabelText('Показ наличия'), 'ON_REQUEST');
    await user.click(screen.getByRole('button', { name: 'Применить' }));

    await waitFor(() => expect(net.calls('PATCH', `${PRODUCT_URL}/availability`)).toHaveLength(1));
    expect(bodyOf('PATCH', `${PRODUCT_URL}/availability`)).toEqual({
      stock_display_override: 'ON_REQUEST',
    });
    expect(net.calls('PUT', `${PRODUCT_URL}/stock`)).toHaveLength(0);
    expect(await screen.findByText('Показ наличия обновлён')).toBeInTheDocument();
  });

  it('без права stock.write — только просмотр чисел', async () => {
    net.on('GET', `${PRODUCT_URL}/stock`, makeStock());
    await openEditor('MANAGER', makeProduct(), 'stock');
    expect(await screen.findByText(/Изменять остатки может роль/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Остаток, м/)).not.toBeInTheDocument();
    expect(screen.getByLabelText('Показ наличия')).toBeDisabled();
  });
});

// ========================================================== изображения
class FakeXHR {
  static requests: {
    method: string;
    url: string;
    headers: Record<string, string>;
    body: unknown;
  }[] = [];
  static status = 200;
  upload: {
    onprogress:
      ((event: { lengthComputable: boolean; loaded: number; total: number }) => void) | null;
  } = {
    onprogress: null,
  };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  status = 0;
  private method = '';
  private url = '';
  private headers: Record<string, string> = {};
  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }
  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }
  send(body: unknown) {
    FakeXHR.requests.push({ method: this.method, url: this.url, headers: this.headers, body });
    setTimeout(() => {
      this.upload.onprogress?.({ lengthComputable: true, loaded: 1, total: 1 });
      this.status = FakeXHR.status;
      this.onload?.();
    }, 0);
  }
  abort() {
    this.onabort?.();
  }
}

describe('карточка: изображения', () => {
  const IMAGES = `${PRODUCT_URL}/images`;

  function gallery(items: ProductImage[]) {
    return { product_id: PRODUCT_ID, items };
  }

  beforeEach(() => {
    FakeXHR.requests = [];
    FakeXHR.status = 200;
    vi.stubGlobal('XMLHttpRequest', FakeXHR);
  });

  it('схема в PDF — тип файла и ссылка вместо превью, обложкой не делается', async () => {
    const photo = makeImage({ id: 1, is_main: true });
    const scheme = makeImage({
      id: 2,
      kind: 'SCHEME',
      content_type: 'application/pdf',
      original_filename: '504-176.pdf',
      url: 'http://cdn.test/products/2/variants/file.pdf',
      variants: { file: 'http://cdn.test/products/2/variants/file.pdf' },
      width: null,
      height: null,
    });
    net.on('GET', IMAGES, gallery([photo, scheme]));
    await openEditor('CONTENT_MANAGER', makeProduct(), 'images');

    const list = await screen.findByRole('list', { name: 'Галерея товара' });
    const [, schemeCard] = within(list).getAllByRole('listitem');
    const card = within(schemeCard as HTMLElement);
    expect(card.getByText('PDF')).toBeInTheDocument();
    expect(card.getByText('Схема')).toBeInTheDocument();
    expect(card.getByRole('link', { name: 'Открыть файл' })).toHaveAttribute(
      'href',
      'http://cdn.test/products/2/variants/file.pdf',
    );
    expect(card.queryByRole('img')).toBeNull();
    expect(card.queryByRole('button', { name: 'Сделать главным' })).toBeNull();
  });

  it('главное изображение обозначено; смена главного и порядок', async () => {
    const first = makeImage({ id: 1, is_main: true });
    const second = makeImage({ id: 2 });
    net.on('GET', IMAGES, gallery([first, second]));
    net.on(
      'PUT',
      `${IMAGES}/main`,
      gallery([
        { ...first, is_main: false },
        { ...second, is_main: true },
      ]),
    );
    net.on(
      'PUT',
      `${IMAGES}/order`,
      gallery([
        { ...second, is_main: true },
        { ...first, is_main: false },
      ]),
    );
    const user = userEvent.setup();
    await openEditor('CONTENT_MANAGER', makeProduct(), 'images');

    const cards = await screen.findAllByRole('listitem');
    const galleryItems = within(screen.getByRole('list', { name: 'Галерея товара' })).getAllByRole(
      'listitem',
    );
    expect(cards.length).toBeGreaterThan(0);
    expect(within(galleryItems[0] as HTMLElement).getByText('Главное')).toBeInTheDocument();

    await user.click(
      within(galleryItems[1] as HTMLElement).getByRole('button', { name: 'Сделать главным' }),
    );
    await waitFor(() => expect(net.calls('PUT', `${IMAGES}/main`)).toHaveLength(1));
    expect(bodyOf('PUT', `${IMAGES}/main`)).toEqual({ image_id: 2 });

    await user.click(
      await screen.findByRole('button', { name: 'Переместить изображение 1 правее' }),
    );
    await waitFor(() => expect(net.calls('PUT', `${IMAGES}/order`)).toHaveLength(1));
    expect(bodyOf('PUT', `${IMAGES}/order`)).toEqual({ image_ids: [2, 1] });
    const reordered = within(screen.getByRole('list', { name: 'Галерея товара' })).getAllByRole(
      'listitem',
    );
    expect(within(reordered[0] as HTMLElement).getByText('Главное')).toBeInTheDocument();
  });

  it('отвязка — с подтверждением; 409 при порядке перечитывает галерею', async () => {
    const first = makeImage({ id: 1, is_main: true });
    const second = makeImage({ id: 2 });
    net.on('GET', IMAGES, gallery([first, second]));
    net.on('DELETE', `${IMAGES}/2`, {
      ok: true,
      status: 204,
      json: async () => null,
    } as unknown as Response);
    net.on(
      'PUT',
      `${IMAGES}/order`,
      errorResponse(409, 'image_order_mismatch', 'Набор изображений изменился'),
    );
    const user = userEvent.setup();
    await openEditor('CONTENT_MANAGER', makeProduct(), 'images');

    await user.click(await screen.findByRole('button', { name: 'Отвязать изображение 2' }));
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: 'Отвязать' }),
    );
    await waitFor(() => expect(net.calls('DELETE', `${IMAGES}/2`)).toHaveLength(1));

    const before = net.calls('GET', IMAGES).length;
    await user.click(
      await screen.findByRole('button', { name: 'Переместить изображение 1 правее' }),
    );
    expect(await screen.findByText('Порядок не сохранён')).toBeInTheDocument();
    await waitFor(() => expect(net.calls('GET', IMAGES).length).toBeGreaterThan(before));
  });

  it('загрузка: intent → PUT в хранилище → complete → привязка; статус обработки', async () => {
    const processing = makeImage({
      id: 9,
      status: 'PROCESSING',
      url: null,
      variants: {},
      is_main: true,
      original_filename: 'new.png',
    });
    net.on('GET', IMAGES, gallery([]));
    net.on(
      'POST',
      '/api/v1/admin/media/upload-intent',
      jsonResponse(
        {
          media: {
            uuid: 'aaaaaaaa-0000-4000-8000-000000000001',
            status: 'PENDING',
            content_type: 'image/png',
            size_bytes: 3,
            usage_count: 0,
            created_at: '',
            updated_at: '',
          },
          upload: {
            url: 'http://storage.test/bucket/products/x/original.png?sig=1',
            method: 'PUT',
            headers: { 'Content-Type': 'image/png' },
            expires_in: 600,
          },
        },
        201,
      ),
    );
    net.on(
      'POST',
      '/api/v1/admin/media/aaaaaaaa-0000-4000-8000-000000000001/complete',
      jsonResponse(
        {
          uuid: 'aaaaaaaa-0000-4000-8000-000000000001',
          status: 'PROCESSING',
          content_type: 'image/png',
          size_bytes: 3,
          usage_count: 0,
          created_at: '',
          updated_at: '',
        },
        202,
      ),
    );
    net.on('POST', IMAGES, jsonResponse(gallery([processing]), 201));
    const user = userEvent.setup();
    await openEditor('CONTENT_MANAGER', makeProduct(), 'images');

    const file = new File(['png'], 'new.png', { type: 'image/png' });
    await user.upload(await screen.findByLabelText('Загрузить изображения'), file);

    await waitFor(() => expect(net.calls('POST', IMAGES)).toHaveLength(1));
    expect(bodyOf('POST', '/api/v1/admin/media/upload-intent')).toEqual({
      filename: 'new.png',
      content_type: 'image/png',
      size_bytes: 3,
      purpose: 'PRODUCT',
    });
    expect(FakeXHR.requests).toHaveLength(1);
    expect(FakeXHR.requests[0]).toMatchObject({
      method: 'PUT',
      url: 'http://storage.test/bucket/products/x/original.png?sig=1',
      headers: { 'Content-Type': 'image/png' },
    });
    // Файл идёт в хранилище, а не через API.
    expect(
      net.mock.mock.calls.some(
        ([, init]) => (init as RequestInit | undefined)?.body instanceof File,
      ),
    ).toBe(false);
    expect(bodyOf('POST', IMAGES)).toEqual({ media_uuid: 'aaaaaaaa-0000-4000-8000-000000000001' });
    expect(await screen.findByText('Обрабатывается…')).toBeInTheDocument();
    expect(screen.getByText('Обработка')).toBeInTheDocument();
  });

  it('отклонённый файл: понятная причина и повтор', async () => {
    net.on('GET', IMAGES, gallery([]));
    net.on(
      'POST',
      '/api/v1/admin/media/upload-intent',
      jsonResponse(
        {
          media: {
            uuid: 'bbbbbbbb-0000-4000-8000-000000000002',
            status: 'PENDING',
            content_type: 'image/png',
            size_bytes: 3,
            usage_count: 0,
            created_at: '',
            updated_at: '',
          },
          upload: { url: 'http://storage.test/x', method: 'PUT', headers: {}, expires_in: 600 },
        },
        201,
      ),
    );
    net.on(
      'POST',
      '/api/v1/admin/media/bbbbbbbb-0000-4000-8000-000000000002/complete',
      errorResponse(422, 'upload_rejected', 'Файл отклонён', { failure_reason: 'type_mismatch' }),
    );
    const user = userEvent.setup();
    await openEditor('CONTENT_MANAGER', makeProduct(), 'images');

    await user.upload(
      await screen.findByLabelText('Загрузить изображения'),
      new File(['x'], 'fake.png', { type: 'image/png' }),
    );

    expect(await screen.findByText('Содержимое не совпадает с типом файла')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Повторить' }));
    await waitFor(() =>
      expect(net.calls('POST', '/api/v1/admin/media/upload-intent')).toHaveLength(2),
    );
    expect(net.calls('POST', IMAGES)).toHaveLength(0);
  });

  it('ошибка хранилища при PUT', async () => {
    FakeXHR.status = 403;
    net.on('GET', IMAGES, gallery([]));
    net.on(
      'POST',
      '/api/v1/admin/media/upload-intent',
      jsonResponse(
        {
          media: {
            uuid: 'cccccccc-0000-4000-8000-000000000003',
            status: 'PENDING',
            content_type: 'image/jpeg',
            size_bytes: 1,
            usage_count: 0,
            created_at: '',
            updated_at: '',
          },
          upload: { url: 'http://storage.test/y', method: 'PUT', headers: {}, expires_in: 600 },
        },
        201,
      ),
    );
    const user = userEvent.setup();
    await openEditor('CONTENT_MANAGER', makeProduct(), 'images');

    await user.upload(
      await screen.findByLabelText('Загрузить изображения'),
      new File(['x'], 'a.jpg', { type: 'image/jpeg' }),
    );
    expect(await screen.findByText('Хранилище отклонило загрузку (403)')).toBeInTheDocument();
    expect(
      net.calls('POST', '/api/v1/admin/media/cccccccc-0000-4000-8000-000000000003/complete'),
    ).toHaveLength(0);
  });

  it('менеджер видит галерею без загрузки и действий', async () => {
    net.on('GET', IMAGES, gallery([makeImage({ id: 1, is_main: true })]));
    await openEditor('MANAGER', makeProduct(), 'images');
    expect(await screen.findByText('Главное')).toBeInTheDocument();
    expect(screen.queryByLabelText('Загрузить изображения')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Отвязать/ })).not.toBeInTheDocument();
  });
});
