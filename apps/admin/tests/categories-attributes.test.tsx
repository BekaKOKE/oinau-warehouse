/**
 * Категории и характеристики: дерево, карточка категории (создание,
 * правка, перенос, удаление, восстановление), характеристики категории,
 * справочник характеристик с вариантами, права и связь с карточкой товара.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AppProviders } from '@/components/AppProviders';
import { AttributesScreen } from '@/components/attributes/AttributesScreen';
import { CategoriesScreen } from '@/components/categories/CategoriesScreen';
import { ProductEditorScreen } from '@/components/products/ProductEditorScreen';
import { AuthGate } from '@/components/session/AuthGate';
import type {
  AttributeRead,
  CategoryAttribute,
  CategoryAttributeItem,
  UserRole,
} from '@/lib/api/types';
import { resetSessionForTests } from '@/lib/auth/session';

import {
  makeAttribute,
  makeCategory,
  makeTree,
  materialAttribute,
  treeNode,
} from './catalog-fixtures';
import { MEDIA, mediaRow, mediaUrl } from './content-fixtures';
import { createFetchMock, errorResponse, jsonResponse, page, signInAs } from './helpers';
import { CATEGORY_TREE, makeProduct, PRODUCT_ID, PRODUCT_URL } from './product-fixtures';
import { navigationState, routerPush, routerReplace } from './setup';

const TREE = '/api/v1/admin/categories/tree';
const CATEGORIES = '/api/v1/admin/categories';
const ATTRIBUTES = '/api/v1/admin/attributes';

const noContent = () => ({ ok: true, status: 204, json: async () => null }) as unknown as Response;

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

function colorAttribute(overrides: Partial<AttributeRead> = {}) {
  return makeAttribute({
    id: 13,
    code: 'color',
    value_type: 'STRING',
    unit: null,
    name: 'Цвет',
    names: { ru: 'Цвет' },
    is_filterable: false,
    ...overrides,
  });
}

const ASSIGNED: CategoryAttribute[] = [
  {
    attribute_id: 10,
    code: 'diameter',
    name: 'Диаметр',
    value_type: 'NUMBER',
    unit: 'мм',
    sort_order: 0,
    is_required: true,
  },
  {
    attribute_id: 11,
    code: 'material',
    name: 'Материал',
    value_type: 'OPTION',
    unit: null,
    sort_order: 1,
    is_required: false,
  },
];

type CategoriesOptions = {
  role?: UserRole;
  search?: string;
  category?: ReturnType<typeof makeCategory>;
  assigned?: CategoryAttribute[];
};

async function openCategories({
  role = 'CONTENT_MANAGER',
  search = '',
  category,
  assigned = ASSIGNED,
}: CategoriesOptions = {}) {
  signInAs(net, role);
  navigationState.pathname = '/categories';
  navigationState.search = search;
  if (!net.calls('GET', TREE).length) net.on('GET', TREE, makeTree());
  if (category) {
    net.on('GET', `${CATEGORIES}/${category.id}`, category);
    net.on('GET', `${CATEGORIES}/${category.id}/attributes`, assigned);
  }
  net.on('GET', ATTRIBUTES, page([makeAttribute(), materialAttribute(), colorAttribute()]));
  renderInPanel(<CategoriesScreen />);
  return screen.findByRole('tree', { name: 'Дерево категорий' });
}

function attributesCard() {
  const heading = screen.getByRole('heading', { name: 'Характеристики категории' });
  return within(heading.closest('section') as HTMLElement);
}

beforeEach(() => {
  resetSessionForTests();
  net = createFetchMock();
  vi.stubGlobal('fetch', net.mock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ================================================================ дерево
describe('дерево категорий', () => {
  it('корни, раскрытие ветки, slug, признаки и счётчики', async () => {
    const user = userEvent.setup();
    const tree = await openCategories();

    expect(within(tree).getByText('Комплектующие')).toBeInTheDocument();
    expect(within(tree).getByText('Сиденья')).toBeInTheDocument();
    expect(within(tree).queryByText('Канаты')).not.toBeInTheDocument();
    expect(screen.getByText('Выберите категорию')).toBeInTheDocument();
    expect(screen.getByText('5 категорий')).toBeInTheDocument();

    const root = screen.getByTestId('category-row-1');
    expect(within(root).getByText('komplektuyushchie')).toBeInTheDocument();
    expect(within(root).getByTitle('Подкатегорий')).toHaveTextContent('2');
    expect(within(root).getByTitle('Товаров')).toHaveTextContent('1');

    await user.click(screen.getByRole('button', { name: 'Развернуть «Комплектующие»' }));
    expect(within(tree).getByText('Канаты')).toBeInTheDocument();
    expect(within(screen.getByTestId('category-row-3')).getByText('Скрыта')).toBeInTheDocument();
    expect(within(screen.getByTestId('category-row-2')).getByTitle('Товаров')).toHaveTextContent(
      '3',
    );
    expect(screen.getAllByRole('treeitem')[0]).toHaveAttribute('aria-expanded', 'true');

    await user.click(screen.getByRole('button', { name: 'Свернуть «Комплектующие»' }));
    expect(within(tree).queryByText('Канаты')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Развернуть всё' }));
    expect(within(tree).getByText('Стальные')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Свернуть' }));
    expect(within(tree).queryByText('Стальные')).not.toBeInTheDocument();
  });

  it('выбор категории — в адрес; клавиатура работает', async () => {
    const user = userEvent.setup();
    await openCategories();
    await user.click(screen.getByText('Сиденья'));
    expect(routerReplace).toHaveBeenCalledWith('/categories?id=5', { scroll: false });

    screen.getByTestId('category-row-1').focus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByText('Канаты')).toBeInTheDocument();
    await user.keyboard('{Enter}');
    expect(routerReplace).toHaveBeenLastCalledWith('/categories?id=1', { scroll: false });
  });

  it('поиск показывает совпадение внутри свёрнутой ветки', async () => {
    const user = userEvent.setup();
    const tree = await openCategories();
    await user.type(screen.getByLabelText('Поиск категории'), 'стальн');
    expect(within(tree).getByText('Стальные')).toBeInTheDocument();
    expect(within(tree).queryByText('Сиденья')).not.toBeInTheDocument();

    await user.clear(screen.getByLabelText('Поиск категории'));
    await user.type(screen.getByLabelText('Поиск категории'), 'нет-такой');
    expect(screen.getByText('Ничего не найдено')).toBeInTheDocument();
  });

  it('«Удалённые» запрашивает include_deleted и помечает удалённые узлы', async () => {
    const user = userEvent.setup();
    await openCategories();
    net.on('GET', TREE, (url: URL) =>
      jsonResponse(
        url.searchParams.get('include_deleted') === 'true'
          ? [
              ...makeTree(),
              treeNode({ id: 9, name: 'Архив', slug: 'arhiv', deleted_at: '2026-09-01T00:00:00Z' }),
            ]
          : makeTree(),
      ),
    );
    await user.click(screen.getByLabelText('Удалённые'));

    const row = await screen.findByTestId('category-row-9');
    expect(within(row).getByText('Удалена')).toBeInTheDocument();
    const calls = net.calls('GET', TREE);
    expect(new URL(String(calls[calls.length - 1]?.[0])).searchParams.get('include_deleted')).toBe(
      'true',
    );
    expect(screen.getByText('5 категорий, удалённых: 1')).toBeInTheDocument();
  });

  it('загрузка, ошибка с повтором, пустое дерево', async () => {
    let release: (value: Response) => void = () => undefined;
    signInAs(net, 'CONTENT_MANAGER');
    net.on('GET', TREE, () => new Promise<Response>((resolve) => (release = resolve)));
    renderInPanel(<CategoriesScreen />);
    expect(await screen.findByTestId('tree-skeleton')).toBeInTheDocument();

    release(errorResponse(500, 'internal_error', 'Сбой'));
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Повторить' }));
    expect(await screen.findByTestId('tree-skeleton')).toBeInTheDocument();
    release(jsonResponse([]));
    expect(await screen.findByText('Категорий пока нет')).toBeInTheDocument();
  });

  it('403 дерева — «Нет доступа»', async () => {
    signInAs(net, 'CONTENT_MANAGER');
    net.on('GET', TREE, errorResponse(403, 'permission_denied', 'Недостаточно прав'));
    renderInPanel(<CategoriesScreen />);
    expect(await screen.findByText('Нет доступа')).toBeInTheDocument();
  });

  it('истёкшая сессия (401) — переход на вход', async () => {
    navigationState.pathname = '/categories';
    window.localStorage.setItem('oinau.admin.session', '1');
    net.on('POST', '/api/v1/admin/auth/refresh', errorResponse(401, 'unauthenticated', 'x'));
    renderInPanel(<CategoriesScreen />);
    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith('/login?next=%2Fcategories'));
  });
});

// ================================================================ создание
describe('создание категории', () => {
  it('подкатегория: родитель подставлен, POST с полным переводом, переход к карточке', async () => {
    net.on('POST', CATEGORIES, makeCategory({ id: 9, name: 'Тросы', slug: 'trosy' }));
    const user = userEvent.setup();
    await openCategories({ search: 'new=1' });

    expect(screen.getByRole('heading', { name: 'Новая категория' })).toBeInTheDocument();
    expect(screen.getByText('Внутри «Комплектующие»')).toBeInTheDocument();
    expect(screen.getByLabelText('Родительская категория')).toHaveValue('1');
    expect(
      screen.getByText('Характеристики назначаются после создания категории.'),
    ).toBeInTheDocument();

    await user.type(screen.getByLabelText(/Название/), 'Тросы');
    // slug новой категории заполняется из названия сам.
    expect(screen.getByLabelText(/Slug/)).toHaveValue('trosy');
    await user.type(screen.getByLabelText('Описание'), 'Стальные тросы');
    await user.click(screen.getByRole('button', { name: 'Создать' }));

    await waitFor(() => expect(net.calls('POST', CATEGORIES)).toHaveLength(1));
    expect(bodyOf('POST', CATEGORIES)).toEqual({
      slug: 'trosy',
      parent_id: 1,
      sort_order: 0,
      is_active: true,
      external_id: null,
      image: null,
      translations: {
        ru: {
          name: 'Тросы',
          description: 'Стальные тросы',
          seo_title: null,
          seo_description: null,
        },
      },
    });
    expect(await screen.findByText('Категория создана')).toBeInTheDocument();
    expect(routerReplace).toHaveBeenCalledWith('/categories?id=9', { scroll: false });
    expect(net.calls('GET', TREE).length).toBeGreaterThan(1);
  });

  it('slug, поправленный руками, больше не идёт за названием', async () => {
    const user = userEvent.setup();
    await openCategories({ search: 'new=' });
    const slug = screen.getByLabelText(/Slug/);

    await user.type(screen.getByLabelText(/Название/), 'Канаты');
    expect(slug).toHaveValue('kanaty');
    await user.clear(slug);
    await user.type(slug, 'ropes');
    await user.type(screen.getByLabelText(/Название/), ' и сети');
    expect(slug).toHaveValue('ropes');
  });

  it('обложку можно загрузить сразу: intent (CONTENT) → PUT → complete → UUID в POST', async () => {
    const MEDIA_UUID = '44444444-4444-4444-8444-444444444444';
    const puts: { method: string; url: string }[] = [];
    vi.stubGlobal(
      'XMLHttpRequest',
      class {
        upload = { onprogress: null };
        onload: (() => void) | null = null;
        onerror: (() => void) | null = null;
        onabort: (() => void) | null = null;
        status = 0;
        private request = { method: '', url: '' };
        open(method: string, url: string) {
          this.request = { method, url };
        }
        setRequestHeader() {}
        send() {
          puts.push(this.request);
          setTimeout(() => {
            this.status = 200;
            this.onload?.();
          }, 0);
        }
        abort() {}
      },
    );
    net.on(
      'POST',
      `${MEDIA}/upload-intent`,
      jsonResponse(
        {
          media: mediaRow({ uuid: MEDIA_UUID, status: 'PENDING', url: null, variants: {} }),
          upload: {
            url: 'http://storage.test/bucket/content/x/original.png?sig=1',
            method: 'PUT',
            headers: {},
            expires_in: 600,
          },
        },
        201,
      ),
    );
    net.on(
      'POST',
      `${mediaUrl(MEDIA_UUID)}/complete`,
      jsonResponse(
        mediaRow({ uuid: MEDIA_UUID, status: 'PROCESSING', url: null, variants: {} }),
        202,
      ),
    );
    net.on('POST', CATEGORIES, makeCategory({ id: 9, name: 'Тросы', slug: 'trosy' }));
    const user = userEvent.setup();
    await openCategories({ search: 'new=' });

    await user.type(screen.getByLabelText(/Название/), 'Тросы');
    const file = new File(['png'], 'cover.png', { type: 'image/png' });
    await user.upload(screen.getByLabelText('Файл обложки'), file);

    expect(
      await screen.findByText('Файл загружен и обрабатывается — превью появится после сохранения.'),
    ).toBeInTheDocument();
    expect(bodyOf('POST', `${MEDIA}/upload-intent`)).toMatchObject({
      filename: 'cover.png',
      purpose: 'CONTENT',
    });
    expect(puts).toEqual([
      { method: 'PUT', url: 'http://storage.test/bucket/content/x/original.png?sig=1' },
    ]);

    await user.click(screen.getByRole('button', { name: 'Создать' }));
    await waitFor(() => expect(net.calls('POST', CATEGORIES)).toHaveLength(1));
    expect(bodyOf('POST', CATEGORIES)).toMatchObject({ image: MEDIA_UUID });
  });

  it('пустые SEO-поля подсказывают, что возьмёт сайт', async () => {
    const user = userEvent.setup();
    await openCategories({ search: 'new=' });
    await user.type(screen.getByLabelText(/Название/), 'Тросы');
    await user.type(screen.getByLabelText('Описание'), 'Стальные тросы');

    expect(screen.getByLabelText('SEO-заголовок')).toHaveAttribute('placeholder', 'Тросы');
    expect(screen.getByLabelText('SEO-описание')).toHaveAttribute('placeholder', 'Стальные тросы');
  });

  it('проверяет поля до отправки', async () => {
    const user = userEvent.setup();
    await openCategories({ search: 'new=' });
    await user.type(screen.getByLabelText(/Slug/), 'Плохой slug');
    await user.click(screen.getByRole('button', { name: 'Создать' }));
    expect(screen.getByLabelText(/Название/)).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByLabelText(/Slug/)).toHaveAttribute('aria-invalid', 'true');
    expect(net.calls('POST', CATEGORIES)).toHaveLength(0);
  });

  it('409 «slug занят» — ошибка у поля slug', async () => {
    net.on('POST', CATEGORIES, errorResponse(409, 'slug_exists', 'Slug «kanaty» уже занят'));
    const user = userEvent.setup();
    await openCategories({ search: 'new=' });
    await user.type(screen.getByLabelText(/Название/), 'Канаты');
    await user.click(screen.getByRole('button', { name: 'Создать' }));

    expect(await screen.findByLabelText(/Slug/)).toHaveAccessibleDescription(
      'Slug «kanaty» уже занят',
    );
    expect(screen.getByText('Категория не создана')).toBeInTheDocument();
  });

  it('422 от backend раскладывается по полям', async () => {
    net.on(
      'POST',
      CATEGORIES,
      errorResponse(422, 'validation_error', 'Ошибка', {
        fields: [{ loc: ['body', 'translations', 'ru', 'seo_title'], msg: 'Слишком длинно' }],
      }),
    );
    const user = userEvent.setup();
    await openCategories({ search: 'new=' });
    await user.type(screen.getByLabelText(/Название/), 'Канаты');
    await user.click(screen.getByRole('button', { name: 'Создать' }));
    expect(await screen.findByLabelText('SEO-заголовок')).toHaveAccessibleDescription(
      'Слишком длинно',
    );
  });
});

// ================================================================ правка
describe('карточка категории', () => {
  it('открывается по адресу, раскрывает предков и показывает факты', async () => {
    await openCategories({ search: 'id=2', category: makeCategory() });
    expect(await screen.findByRole('heading', { name: 'Канаты' })).toBeInTheDocument();
    // Карточка и дерево грузятся разными запросами: заголовок карточки
    // появляется раньше, чем дерево успевает раскрыть ветку.
    expect(await screen.findByTestId('category-row-2')).toBeInTheDocument();
    expect(screen.getByRole('treeitem', { selected: true })).toHaveTextContent('Канаты');
    expect(screen.getByText('Комплектующие / Канаты')).toBeInTheDocument();
    expect(screen.getByText('3 товара')).toBeInTheDocument();
    expect(screen.getByText('1 подкатегория')).toBeInTheDocument();
    expect(screen.getByLabelText(/Slug/)).toHaveValue('kanaty');
    expect(screen.getByLabelText('SEO-заголовок')).toHaveValue('Канаты SEO');
  });

  it('родителем нельзя выбрать саму категорию и её потомков', async () => {
    await openCategories({ search: 'id=2', category: makeCategory() });
    const select = await screen.findByLabelText('Родительская категория');
    const values = within(select)
      .getAllByRole('option')
      .map((option) => (option as HTMLOptionElement).value);
    expect(values).toEqual(['', '1', '3', '5']);
    expect(select).toHaveValue('1');
  });

  it('сохраняет изменённое название полным переводом', async () => {
    net.on(
      'PATCH',
      `${CATEGORIES}/2`,
      makeCategory({ name: 'Канаты стальные', updated_at: '2026-09-14T00:00:00Z' }),
    );
    const user = userEvent.setup();
    await openCategories({ search: 'id=2', category: makeCategory() });
    const name = await screen.findByLabelText(/Название/);
    expect(screen.getByRole('button', { name: 'Сохранить' })).toBeDisabled();
    await user.type(name, ' стальные');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(net.calls('PATCH', `${CATEGORIES}/2`)).toHaveLength(1));
    expect(bodyOf('PATCH', `${CATEGORIES}/2`)).toEqual({
      translations: {
        ru: {
          name: 'Канаты стальные',
          description: 'Канаты для площадок',
          seo_title: 'Канаты SEO',
          seo_description: null,
        },
      },
    });
    expect(await screen.findByText('Изменения сохранены')).toBeInTheDocument();
  });

  it('перенос ветки: подтверждение и PATCH только parent_id', async () => {
    net.on(
      'PATCH',
      `${CATEGORIES}/2`,
      makeCategory({ parent_id: 5, updated_at: '2026-09-14T00:00:00Z' }),
    );
    const user = userEvent.setup();
    await openCategories({ search: 'id=2', category: makeCategory() });
    await user.selectOptions(await screen.findByLabelText('Родительская категория'), '5');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));

    const dialog = await screen.findByRole('dialog', { name: 'Перенести ветку?' });
    await user.click(within(dialog).getByRole('button', { name: 'Перенести' }));
    await waitFor(() => expect(net.calls('PATCH', `${CATEGORIES}/2`)).toHaveLength(1));
    expect(bodyOf('PATCH', `${CATEGORIES}/2`)).toEqual({ parent_id: 5 });
  });

  it('отказ от переноса ничего не отправляет; перенос в корень — parent_id null', async () => {
    net.on(
      'PATCH',
      `${CATEGORIES}/2`,
      makeCategory({ parent_id: null, updated_at: '2026-09-14T00:00:00Z' }),
    );
    const user = userEvent.setup();
    await openCategories({ search: 'id=2', category: makeCategory() });
    await user.selectOptions(await screen.findByLabelText('Родительская категория'), '');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: 'Отмена' }),
    );
    expect(net.calls('PATCH', `${CATEGORIES}/2`)).toHaveLength(0);

    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: 'Перенести' }),
    );
    await waitFor(() => expect(net.calls('PATCH', `${CATEGORIES}/2`)).toHaveLength(1));
    expect(bodyOf('PATCH', `${CATEGORIES}/2`)).toEqual({ parent_id: null });
  });

  it('409 цикла — ошибка у поля родителя', async () => {
    net.on(
      'PATCH',
      `${CATEGORIES}/5`,
      errorResponse(409, 'category_cycle', 'Нельзя перенести категорию внутрь её ветки'),
    );
    const user = userEvent.setup();
    await openCategories({
      search: 'id=5',
      category: makeCategory({
        id: 5,
        slug: 'sideniya',
        name: 'Сиденья',
        parent_id: null,
        path: '5',
        depth: 0,
      }),
    });
    await user.selectOptions(await screen.findByLabelText('Родительская категория'), '4');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findByLabelText('Родительская категория')).toHaveAccessibleDescription(
      'Нельзя перенести категорию внутрь её ветки',
    );
  });

  it('403 при сохранении не маскируется', async () => {
    net.on(
      'PATCH',
      `${CATEGORIES}/2`,
      errorResponse(403, 'permission_denied', 'Недостаточно прав'),
    );
    const user = userEvent.setup();
    await openCategories({ search: 'id=2', category: makeCategory() });
    await user.type(await screen.findByLabelText('Порядок'), '5');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findByText('Нет права изменять категории')).toBeInTheDocument();
  });

  it('несуществующая категория — понятное сообщение', async () => {
    signInAs(net, 'CONTENT_MANAGER');
    navigationState.search = 'id=99';
    net.on('GET', TREE, makeTree());
    net.on('GET', `${CATEGORIES}/99`, errorResponse(404, 'not_found', 'Категория не найдена'));
    renderInPanel(<CategoriesScreen />);
    expect(
      await screen.findByText('Категория не найдена — возможно, ссылка устарела.'),
    ).toBeInTheDocument();
  });

  it('«Подкатегория» открывает создание внутри текущей', async () => {
    const user = userEvent.setup();
    await openCategories({ search: 'id=2', category: makeCategory() });
    await user.click(await screen.findByRole('button', { name: 'Подкатегория' }));
    expect(routerReplace).toHaveBeenCalledWith('/categories?new=2', { scroll: false });
  });
});

// ================================================================ удаление
describe('удаление и восстановление категории', () => {
  const steel = makeCategory({
    id: 4,
    slug: 'stalnye',
    name: 'Стальные',
    parent_id: 2,
    path: '1.2.4',
    depth: 2,
    products_count: 0,
  });

  it('удаление — подтверждение, DELETE и режим удалённой категории', async () => {
    const user = userEvent.setup();
    await openCategories({ search: 'id=4', category: steel, assigned: [] });
    net.on('DELETE', `${CATEGORIES}/4`, noContent);
    net.on('GET', `${CATEGORIES}/4`, { ...steel, deleted_at: '2026-09-14T10:00:00Z' });

    await user.click(await screen.findByRole('button', { name: 'Удалить' }));
    const dialog = await screen.findByRole('dialog', { name: 'Удалить категорию «Стальные»?' });
    expect(dialog).toHaveTextContent('без подкатегорий и без товаров');
    await user.click(within(dialog).getByRole('button', { name: 'Удалить' }));

    await waitFor(() => expect(net.calls('DELETE', `${CATEGORIES}/4`)).toHaveLength(1));
    expect(await screen.findByRole('button', { name: 'Восстановить' })).toBeInTheDocument();
    expect(screen.getByText(/Удалена 14\.09\.2026/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Название/)).toBeDisabled();
    expect(
      screen.queryByRole('button', { name: 'Сохранить характеристики' }),
    ).not.toBeInTheDocument();
  });

  it('409: есть подкатегории / есть товары — объяснение, категория остаётся', async () => {
    const user = userEvent.setup();
    await openCategories({ search: 'id=2', category: makeCategory() });
    net.on(
      'DELETE',
      `${CATEGORIES}/2`,
      errorResponse(409, 'category_has_children', 'Есть подкатегории'),
    );
    await user.click(await screen.findByRole('button', { name: 'Удалить' }));
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: 'Удалить' }),
    );
    expect(
      await screen.findByText('Сначала удалите или перенесите подкатегории'),
    ).toBeInTheDocument();

    net.on('DELETE', `${CATEGORIES}/2`, errorResponse(409, 'category_has_products', 'Есть товары'));
    await user.click(screen.getByRole('button', { name: 'Удалить' }));
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: 'Удалить' }),
    );
    expect(
      await screen.findByText('В категории есть товары — перенесите их в другой раздел'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Восстановить' })).not.toBeInTheDocument();
  });

  it('403 при удалении', async () => {
    const user = userEvent.setup();
    await openCategories({ search: 'id=4', category: steel, assigned: [] });
    net.on(
      'DELETE',
      `${CATEGORIES}/4`,
      errorResponse(403, 'permission_denied', 'Недостаточно прав'),
    );
    await user.click(await screen.findByRole('button', { name: 'Удалить' }));
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: 'Удалить' }),
    );
    expect(await screen.findByText('Нет права удалять категории')).toBeInTheDocument();
  });

  it('восстановление: POST restore, скрытая категория — подсказка', async () => {
    const deleted = { ...steel, is_active: false, deleted_at: '2026-09-14T10:00:00Z' };
    net.on('POST', `${CATEGORIES}/4/restore`, { ...deleted, deleted_at: null });
    const user = userEvent.setup();
    await openCategories({ search: 'id=4', category: deleted, assigned: [] });
    await user.click(await screen.findByRole('button', { name: 'Восстановить' }));

    await waitFor(() => expect(net.calls('POST', `${CATEGORIES}/4/restore`)).toHaveLength(1));
    expect(await screen.findByText('Категория восстановлена')).toBeInTheDocument();
    expect(screen.getByText(/включите «Активна»/)).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Удалить' })).toBeInTheDocument();
    expect(screen.getByLabelText(/Название/)).toBeEnabled();
  });

  it('409 при восстановлении: slug занят / родитель удалён', async () => {
    const deleted = { ...steel, deleted_at: '2026-09-14T10:00:00Z' };
    net.on('POST', `${CATEGORIES}/4/restore`, errorResponse(409, 'slug_exists', 'Slug занят'));
    const user = userEvent.setup();
    await openCategories({ search: 'id=4', category: deleted, assigned: [] });
    await user.click(await screen.findByRole('button', { name: 'Восстановить' }));
    expect(
      await screen.findByText('Slug уже занят другой категорией — восстановление невозможно'),
    ).toBeInTheDocument();

    net.on(
      'POST',
      `${CATEGORIES}/4/restore`,
      errorResponse(409, 'parent_deleted', 'Родитель удалён'),
    );
    await user.click(screen.getByRole('button', { name: 'Восстановить' }));
    expect(
      await screen.findByText('Родительская категория удалена — сначала восстановите её'),
    ).toBeInTheDocument();
  });
});

// ================================================================ права
describe('права на категории', () => {
  it('менеджер: только просмотр дерева, карточки и характеристик', async () => {
    await openCategories({ role: 'MANAGER', search: 'id=2', category: makeCategory() });
    expect(screen.queryByRole('button', { name: 'Новая категория' })).not.toBeInTheDocument();
    expect(await screen.findByText(/Только просмотр/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Название/)).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Сохранить' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Удалить' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Подкатегория' })).not.toBeInTheDocument();

    const list = await screen.findByRole('list', { name: 'Назначенные характеристики' });
    expect(within(list).getByText('Диаметр, мм')).toBeInTheDocument();
    expect(within(list).getAllByRole('checkbox')[0]).toBeDisabled();
    expect(
      screen.queryByRole('button', { name: 'Сохранить характеристики' }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Добавить характеристику')).not.toBeInTheDocument();
    expect(net.calls('GET', ATTRIBUTES)).toHaveLength(0);
  });

  it('VIEWER не может открыть создание по ссылке', async () => {
    await openCategories({ role: 'VIEWER', search: 'new=1' });
    expect(screen.queryByRole('heading', { name: 'Новая категория' })).not.toBeInTheDocument();
    expect(screen.getByText('Выберите категорию')).toBeInTheDocument();
  });

  it('удалённая категория у редактора — характеристики только для просмотра', async () => {
    await openCategories({
      search: 'id=2',
      category: makeCategory({ deleted_at: '2026-09-14T10:00:00Z' }),
    });
    await screen.findByRole('list', { name: 'Назначенные характеристики' });
    expect(screen.queryByRole('button', { name: 'Убрать «Диаметр»' })).not.toBeInTheDocument();
  });
});

// ================================================================ характеристики категории
describe('характеристики категории', () => {
  it('загрузка в порядке sort_order, признак обязательной', async () => {
    await openCategories({
      search: 'id=2',
      category: makeCategory(),
      assigned: [ASSIGNED[1]!, ASSIGNED[0]!],
    });
    const list = await screen.findByRole('list', { name: 'Назначенные характеристики' });
    const items = within(list).getAllByRole('listitem');
    expect(items[0]).toHaveTextContent('Диаметр, мм');
    expect(items[0]).toHaveTextContent('Число');
    expect(items[1]).toHaveTextContent('Материал');
    expect(within(items[0]!).getByLabelText('Обязательная')).toBeChecked();
    expect(within(items[1]!).getByLabelText('Обязательная')).not.toBeChecked();
    expect(screen.getByRole('button', { name: 'Поднять «Диаметр»' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Сохранить характеристики' })).toBeDisabled();
  });

  it('добавить, убрать, переставить, отметить обязательной и сохранить набор целиком', async () => {
    const saved: CategoryAttribute[] = [
      { ...ASSIGNED[1]!, sort_order: 0, is_required: true },
      {
        attribute_id: 13,
        code: 'color',
        name: 'Цвет',
        value_type: 'STRING',
        unit: null,
        sort_order: 1,
        is_required: false,
      },
    ];
    net.on('PUT', `${CATEGORIES}/2/attributes`, saved);
    const user = userEvent.setup();
    await openCategories({ search: 'id=2', category: makeCategory() });
    const select = await screen.findByLabelText('Добавить характеристику');
    await waitFor(() => expect(select).toBeEnabled());

    // Уже назначенных в списке добавления нет.
    const offered = within(select)
      .getAllByRole('option')
      .map((option) => option.textContent);
    expect(offered).toEqual(['Выберите характеристику', 'Цвет (color) — Текст']);

    await user.selectOptions(select, '13');
    await user.click(screen.getByRole('button', { name: 'Добавить' }));
    await user.click(screen.getByRole('button', { name: 'Убрать «Диаметр»' }));
    await user.click(screen.getByRole('button', { name: 'Поднять «Цвет»' }));
    await user.click(screen.getByRole('button', { name: 'Поднять «Цвет»' }));
    await user.click(screen.getByRole('button', { name: 'Опустить «Цвет»' }));

    const list = screen.getByRole('list', { name: 'Назначенные характеристики' });
    await user.click(
      within(within(list).getAllByRole('listitem')[0]!).getByLabelText('Обязательная'),
    );
    expect(screen.getByText('Есть несохранённые изменения')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Сохранить характеристики' }));
    await waitFor(() => expect(net.calls('PUT', `${CATEGORIES}/2/attributes`)).toHaveLength(1));
    const expected: { items: CategoryAttributeItem[] } = {
      items: [
        { attribute_id: 11, sort_order: 0, is_required: true },
        { attribute_id: 13, sort_order: 1, is_required: false },
      ],
    };
    expect(bodyOf('PUT', `${CATEGORIES}/2/attributes`)).toEqual(expected);
    expect(await screen.findByText('Характеристики категории сохранены')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Сохранить характеристики' })).toBeDisabled();
  });

  it('«Отменить» возвращает сохранённый набор; пустой набор тоже сохраняется', async () => {
    net.on('PUT', `${CATEGORIES}/2/attributes`, []);
    const user = userEvent.setup();
    await openCategories({ search: 'id=2', category: makeCategory() });
    await user.click(await screen.findByRole('button', { name: 'Убрать «Диаметр»' }));
    await user.click(attributesCard().getByRole('button', { name: 'Отменить' }));
    expect(screen.getByText('Диаметр, мм')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Убрать «Диаметр»' }));
    await user.click(screen.getByRole('button', { name: 'Убрать «Материал»' }));
    expect(screen.getByText('Характеристики не назначены')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Сохранить характеристики' }));
    await waitFor(() => expect(bodyOf('PUT', `${CATEGORIES}/2/attributes`)).toEqual({ items: [] }));
  });

  it('ошибки: 404 характеристики, 403, сбой загрузки', async () => {
    const user = userEvent.setup();
    await openCategories({ search: 'id=2', category: makeCategory() });
    net.on(
      'PUT',
      `${CATEGORIES}/2/attributes`,
      errorResponse(404, 'not_found', 'Характеристика 11 не найдена'),
    );
    await user.click(
      await screen.findByLabelText('Обязательная', { selector: 'input:not(:checked)' }),
    );
    await user.click(screen.getByRole('button', { name: 'Сохранить характеристики' }));
    expect(await attributesCard().findByRole('alert')).toHaveTextContent(
      'Характеристика 11 не найдена',
    );
    expect(screen.getByText('Есть несохранённые изменения')).toBeInTheDocument();

    net.on(
      'PUT',
      `${CATEGORIES}/2/attributes`,
      errorResponse(403, 'permission_denied', 'Недостаточно прав'),
    );
    await user.click(screen.getByRole('button', { name: 'Сохранить характеристики' }));
    expect(await screen.findByText('Нет права изменять категории')).toBeInTheDocument();
  });

  it('сбой загрузки назначенных — ошибка с повтором', async () => {
    signInAs(net, 'CONTENT_MANAGER');
    navigationState.search = 'id=2';
    net.on('GET', TREE, makeTree());
    net.on('GET', `${CATEGORIES}/2`, makeCategory());
    net.on('GET', `${CATEGORIES}/2/attributes`, errorResponse(500, 'internal_error', 'Сбой'));
    net.on('GET', ATTRIBUTES, page([]));
    renderInPanel(<CategoriesScreen />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Повторить' }));
    net.on('GET', `${CATEGORIES}/2/attributes`, ASSIGNED);
    await user.click(await screen.findByRole('button', { name: 'Повторить' }));
    expect(await screen.findByText('Диаметр, мм')).toBeInTheDocument();
  });
});

// ================================================================ справочник характеристик
async function openAttributes(
  role: UserRole = 'CONTENT_MANAGER',
  items = [
    makeAttribute(),
    materialAttribute(),
    colorAttribute({ is_active: false, is_visible: false }),
  ],
) {
  signInAs(net, role);
  navigationState.pathname = '/attributes';
  net.on('GET', ATTRIBUTES, page(items));
  renderInPanel(<AttributesScreen />);
  return screen.findByRole('table', { name: 'Характеристики' });
}

describe('список характеристик', () => {
  it('строки: название, код, тип, варианты, категории, использование, статус', async () => {
    const table = await openAttributes();
    await within(table).findByRole('button', { name: 'Диаметр, мм' });
    const rows = within(table).getAllByRole('row');
    const diameter = within(rows[1]!);
    expect(diameter.getByRole('button', { name: 'Диаметр, мм' })).toBeInTheDocument();
    expect(diameter.getByText('diameter')).toBeInTheDocument();
    expect(diameter.getByText('Число')).toBeInTheDocument();
    expect(diameter.getByText('Не назначена')).toBeInTheDocument();
    expect(diameter.getByText('Активна')).toBeInTheDocument();
    expect(diameter.getByText('Фильтр')).toBeInTheDocument();

    const material = within(rows[2]!);
    expect(material.getByText('Список')).toBeInTheDocument();
    expect(material.getByText('2')).toBeInTheDocument();
    expect(material.getByText('Канаты')).toBeInTheDocument();
    expect(material.getByText('4')).toBeInTheDocument();

    const color = within(rows[3]!);
    expect(color.getByText('Отключена')).toBeInTheDocument();
    expect(color.getByText('Скрыта на сайте')).toBeInTheDocument();
    expect(screen.getByText('3 характеристики')).toBeInTheDocument();
  });

  it('поиск и статус уходят в адрес', async () => {
    const user = userEvent.setup();
    await openAttributes();
    await user.type(screen.getByLabelText('Поиск'), 'диам');
    await waitFor(() =>
      expect(routerReplace).toHaveBeenCalledWith('/attributes?search=%D0%B4%D0%B8%D0%B0%D0%BC', {
        scroll: false,
      }),
    );
    await user.selectOptions(screen.getByLabelText('Статус'), 'false');
    expect(routerReplace).toHaveBeenLastCalledWith(expect.stringContaining('is_active=false'), {
      scroll: false,
    });
  });

  it('параметры адреса — в запрос; пусто при фильтре — «Ничего не найдено»', async () => {
    navigationState.search = 'search=zzz&is_active=true&page=2';
    const table = await openAttributes('CONTENT_MANAGER', []);
    expect(await within(table).findByText('Ничего не найдено')).toBeInTheDocument();
    const params = new URL(String(net.calls('GET', ATTRIBUTES)[0]?.[0])).searchParams;
    expect(params.get('search')).toBe('zzz');
    expect(params.get('is_active')).toBe('true');
    expect(params.get('page')).toBe('2');
    expect(params.get('page_size')).toBe('24');
  });

  it('пустой справочник и ошибка с повтором', async () => {
    let calls = 0;
    signInAs(net, 'CONTENT_MANAGER');
    net.on('GET', ATTRIBUTES, () => {
      calls += 1;
      return calls === 1 ? errorResponse(500, 'internal_error', 'Сбой') : jsonResponse(page([]));
    });
    renderInPanel(<AttributesScreen />);
    const table = await screen.findByRole('table', { name: 'Характеристики' });
    await userEvent.setup().click(await within(table).findByRole('button', { name: 'Повторить' }));
    expect(await within(table).findByText('Характеристик пока нет')).toBeInTheDocument();
  });

  it('403 списка — «Нет доступа»', async () => {
    signInAs(net, 'CONTENT_MANAGER');
    net.on('GET', ATTRIBUTES, errorResponse(403, 'permission_denied', 'Недостаточно прав'));
    renderInPanel(<AttributesScreen />);
    const table = await screen.findByRole('table', { name: 'Характеристики' });
    expect(await within(table).findByText('Нет доступа')).toBeInTheDocument();
  });
});

describe('создание характеристики', () => {
  it('текстовая: POST без вариантов', async () => {
    net.on('POST', ATTRIBUTES, (_url: URL, init: RequestInit) =>
      jsonResponse(
        colorAttribute({ id: 20, code: 'surface', name: JSON.parse(String(init.body)).names.ru }),
        201,
      ),
    );
    const user = userEvent.setup();
    await openAttributes();
    await user.click(screen.getByRole('button', { name: 'Новая характеристика' }));
    const drawer = await screen.findByRole('dialog', { name: 'Новая характеристика' });

    await user.type(within(drawer).getByLabelText(/Название/), 'Покрытие');
    await user.type(within(drawer).getByLabelText(/Код/), 'surface');
    await user.selectOptions(within(drawer).getByLabelText(/Тип значения/), 'STRING');
    await user.click(within(drawer).getByRole('button', { name: 'Создать' }));

    await waitFor(() => expect(net.calls('POST', ATTRIBUTES)).toHaveLength(1));
    expect(bodyOf('POST', ATTRIBUTES)).toEqual({
      code: 'surface',
      value_type: 'STRING',
      unit: null,
      is_filterable: true,
      is_visible: true,
      is_active: true,
      sort_order: 0,
      names: { ru: 'Покрытие' },
      options: [],
    });
    expect(await screen.findByText('Характеристика создана')).toBeInTheDocument();
    // После создания код и тип — только для чтения.
    const created = await screen.findByRole('dialog', { name: 'Покрытие' });
    expect(within(created).getByTestId('immutable-fields')).toHaveTextContent('surface');
    expect(within(created).queryByLabelText(/Тип значения/)).not.toBeInTheDocument();
  });

  it('список: варианты задаются сразу, slug из значения', async () => {
    net.on('POST', ATTRIBUTES, materialAttribute({ id: 21, usage_count: 0, categories: [] }));
    const user = userEvent.setup();
    await openAttributes();
    await user.click(screen.getByRole('button', { name: 'Новая характеристика' }));
    const drawer = await screen.findByRole('dialog', { name: 'Новая характеристика' });

    await user.type(within(drawer).getByLabelText(/Название/), 'Материал');
    await user.type(within(drawer).getByLabelText(/Код/), 'material');
    await user.selectOptions(within(drawer).getByLabelText(/Тип значения/), 'OPTION');
    await user.click(within(drawer).getByRole('button', { name: 'Добавить вариант' }));
    await user.click(within(drawer).getByRole('button', { name: 'Добавить вариант' }));
    await user.type(within(drawer).getByLabelText('Вариант 1'), 'Сталь');
    const slugs = within(drawer).getAllByLabelText('slug');
    await user.clear(slugs[0]!);
    await user.type(slugs[0]!, 'steel');
    await user.type(within(drawer).getByLabelText('Вариант 2'), 'pp');

    await user.click(within(drawer).getByRole('button', { name: 'Создать' }));
    await waitFor(() => expect(net.calls('POST', ATTRIBUTES)).toHaveLength(1));
    expect(bodyOf('POST', ATTRIBUTES)).toMatchObject({
      code: 'material',
      value_type: 'OPTION',
      options: [
        { slug: 'steel', sort_order: 0, values: { ru: 'Сталь' } },
        { slug: 'pp', sort_order: 1, values: { ru: 'pp' } },
      ],
    });
    // Созданная характеристика-список управляет вариантами отдельно.
    expect(await screen.findByRole('list', { name: 'Варианты значений' })).toBeInTheDocument();
  });

  it('пустой вариант и неверный код не отправляются', async () => {
    const user = userEvent.setup();
    await openAttributes();
    await user.click(screen.getByRole('button', { name: 'Новая характеристика' }));
    const drawer = await screen.findByRole('dialog', { name: 'Новая характеристика' });
    await user.type(within(drawer).getByLabelText(/Название/), 'Материал');
    await user.type(within(drawer).getByLabelText(/Код/), 'Material-X');
    await user.selectOptions(within(drawer).getByLabelText(/Тип значения/), 'OPTION');
    await user.click(within(drawer).getByRole('button', { name: 'Добавить вариант' }));
    await user.click(within(drawer).getByRole('button', { name: 'Создать' }));

    expect(within(drawer).getByLabelText(/Код/)).toHaveAttribute('aria-invalid', 'true');
    expect(within(drawer).getByLabelText('Вариант 1')).toHaveAttribute('aria-invalid', 'true');
    expect(net.calls('POST', ATTRIBUTES)).toHaveLength(0);
  });

  it('409 «код занят» — у поля кода', async () => {
    net.on(
      'POST',
      ATTRIBUTES,
      errorResponse(409, 'attribute_code_exists', 'Код «diameter» уже занят'),
    );
    const user = userEvent.setup();
    await openAttributes();
    await user.click(screen.getByRole('button', { name: 'Новая характеристика' }));
    const drawer = await screen.findByRole('dialog', { name: 'Новая характеристика' });
    await user.type(within(drawer).getByLabelText(/Название/), 'Диаметр');
    await user.type(within(drawer).getByLabelText(/Код/), 'diameter');
    await user.click(within(drawer).getByRole('button', { name: 'Создать' }));
    expect(await within(drawer).findByLabelText(/Код/)).toHaveAccessibleDescription(
      'Код «diameter» уже занят',
    );
  });
});

describe('карточка характеристики', () => {
  async function openDrawer(attribute: AttributeRead, role: UserRole = 'CONTENT_MANAGER') {
    const user = userEvent.setup();
    const table = await openAttributes(role, [attribute]);
    await user.click(
      await within(table).findByRole('button', { name: new RegExp(attribute.name) }),
    );
    const drawer = await screen.findByRole('dialog', { name: attribute.name });
    return { user, drawer };
  }

  it('тип значения и код не меняются: полей нет, PATCH без них', async () => {
    net.on('PATCH', `${ATTRIBUTES}/10`, makeAttribute({ name: 'Диаметр наружный', unit: 'см' }));
    const { user, drawer } = await openDrawer(makeAttribute());

    const facts = within(drawer).getByTestId('immutable-fields');
    expect(facts).toHaveTextContent('diameter');
    expect(facts).toHaveTextContent('Число');
    expect(facts).toHaveTextContent('Не меняется');
    expect(within(drawer).queryByLabelText(/Тип значения/)).not.toBeInTheDocument();
    expect(within(drawer).queryByLabelText(/^Код/)).not.toBeInTheDocument();

    await user.type(within(drawer).getByLabelText(/Название/), ' наружный');
    await user.clear(within(drawer).getByLabelText('Единица измерения'));
    await user.type(within(drawer).getByLabelText('Единица измерения'), 'см');
    await user.click(within(drawer).getByLabelText('Фильтр в каталоге'));
    await user.click(within(drawer).getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(net.calls('PATCH', `${ATTRIBUTES}/10`)).toHaveLength(1));
    const body = bodyOf('PATCH', `${ATTRIBUTES}/10`);
    expect(body).toEqual({ names: { ru: 'Диаметр наружный' }, unit: 'см', is_filterable: false });
    expect(await screen.findByText('Изменения сохранены')).toBeInTheDocument();
    expect(net.calls('GET', ATTRIBUTES).length).toBeGreaterThan(1);
  });

  it('где используется: категории со ссылкой в раздел категорий', async () => {
    const { user, drawer } = await openDrawer(materialAttribute());
    await user.click(within(drawer).getByRole('button', { name: 'Канаты' }));
    expect(routerPush).toHaveBeenCalledWith('/categories?id=2');
  });

  it('удаление: подтверждение перечисляет категории; 409 «используется»', async () => {
    net.on(
      'DELETE',
      `${ATTRIBUTES}/11`,
      errorResponse(409, 'attribute_in_use', 'Есть значения у товаров'),
    );
    const { user, drawer } = await openDrawer(materialAttribute());
    await user.click(within(drawer).getByRole('button', { name: 'Удалить характеристику' }));
    const dialog = await screen.findByRole('dialog', {
      name: 'Удалить характеристику «Материал»?',
    });
    expect(dialog).toHaveTextContent('Канаты');
    await user.click(within(dialog).getByRole('button', { name: 'Удалить' }));
    expect(
      await screen.findByText(
        'Характеристика используется в товарах — отключите её вместо удаления',
      ),
    ).toBeInTheDocument();
  });

  it('удаление неиспользуемой — DELETE и обновление списка', async () => {
    net.on('DELETE', `${ATTRIBUTES}/10`, noContent);
    const { user, drawer } = await openDrawer(makeAttribute());
    await user.click(within(drawer).getByRole('button', { name: 'Удалить характеристику' }));
    await user.click(
      within(await screen.findByRole('dialog', { name: /Удалить характеристику/ })).getByRole(
        'button',
        { name: 'Удалить' },
      ),
    );
    await waitFor(() => expect(net.calls('DELETE', `${ATTRIBUTES}/10`)).toHaveLength(1));
    expect(await screen.findByText('Характеристика удалена')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(net.calls('GET', ATTRIBUTES)).toHaveLength(2);
  });

  it('403 при сохранении и удалении', async () => {
    net.on(
      'PATCH',
      `${ATTRIBUTES}/10`,
      errorResponse(403, 'permission_denied', 'Недостаточно прав'),
    );
    net.on(
      'DELETE',
      `${ATTRIBUTES}/10`,
      errorResponse(403, 'permission_denied', 'Недостаточно прав'),
    );
    const { user, drawer } = await openDrawer(makeAttribute());
    await user.type(within(drawer).getByLabelText('Порядок'), '0');
    await user.click(within(drawer).getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findByText('Нет права изменять характеристики')).toBeInTheDocument();

    await user.click(within(drawer).getByRole('button', { name: 'Удалить характеристику' }));
    await user.click(
      within(await screen.findByRole('dialog', { name: /Удалить характеристику/ })).getByRole(
        'button',
        { name: 'Удалить' },
      ),
    );
    expect(await screen.findByText('Нет права удалять характеристики')).toBeInTheDocument();
  });

  it('менеджер: только просмотр, без вариантов и удаления', async () => {
    const { drawer } = await openDrawer(materialAttribute(), 'MANAGER');
    expect(screen.queryByRole('button', { name: 'Новая характеристика' })).not.toBeInTheDocument();
    expect(within(drawer).getByText(/Только просмотр/)).toBeInTheDocument();
    expect(within(drawer).getByLabelText(/Название/)).toBeDisabled();
    expect(within(drawer).queryByRole('button', { name: 'Сохранить' })).not.toBeInTheDocument();
    expect(
      within(drawer).queryByRole('button', { name: 'Удалить характеристику' }),
    ).not.toBeInTheDocument();
    expect(within(drawer).queryByLabelText('Новый вариант')).not.toBeInTheDocument();
    expect(
      within(drawer).queryByRole('button', { name: /Удалить вариант/ }),
    ).not.toBeInTheDocument();
    expect(within(drawer).getAllByLabelText('Значение')[0]).toBeDisabled();
  });
});

describe('варианты значений', () => {
  async function openMaterial() {
    const user = userEvent.setup();
    const table = await openAttributes('CONTENT_MANAGER', [materialAttribute()]);
    await user.click(await within(table).findByRole('button', { name: 'Материал' }));
    const drawer = await screen.findByRole('dialog', { name: 'Материал' });
    return { user, drawer };
  }

  it('добавление: POST варианта и перечитывание характеристики', async () => {
    const withRubber = materialAttribute({
      options: [
        ...materialAttribute().options!,
        { id: 102, slug: 'rubber', sort_order: 2, values: { ru: 'Резина' } },
      ],
    });
    net.on('POST', `${ATTRIBUTES}/11/options`, {
      id: 102,
      slug: 'rubber',
      sort_order: 2,
      values: { ru: 'Резина' },
    });
    net.on('GET', `${ATTRIBUTES}/11`, withRubber);
    const { user, drawer } = await openMaterial();

    await user.type(within(drawer).getByLabelText('Новый вариант'), 'Резина');
    const slugs = within(drawer).getAllByLabelText('slug');
    await user.clear(slugs[slugs.length - 1]!);
    await user.type(slugs[slugs.length - 1]!, 'rubber');
    await user.click(within(drawer).getByRole('button', { name: 'Добавить' }));

    await waitFor(() => expect(net.calls('POST', `${ATTRIBUTES}/11/options`)).toHaveLength(1));
    expect(bodyOf('POST', `${ATTRIBUTES}/11/options`)).toEqual({
      slug: 'rubber',
      sort_order: 2,
      values: { ru: 'Резина' },
    });
    const list = await within(drawer).findByRole('list', { name: 'Варианты значений' });
    await waitFor(() => expect(within(list).getAllByRole('listitem')).toHaveLength(3));
    expect(screen.getByText('Вариант добавлен')).toBeInTheDocument();
  });

  it('правка: PATCH только изменённого; 409 slug — у поля', async () => {
    net.on(
      'PATCH',
      `${ATTRIBUTES}/11/options/101`,
      errorResponse(409, 'slug_exists', 'Slug варианта занят'),
    );
    const { user, drawer } = await openMaterial();
    const list = within(drawer).getByRole('list', { name: 'Варианты значений' });
    const steel = within(within(list).getAllByRole('listitem')[1]!);

    await user.clear(steel.getByLabelText('slug'));
    await user.type(steel.getByLabelText('slug'), 'pp');
    await user.click(steel.getByRole('button', { name: 'Сохранить' }));
    expect(await steel.findByLabelText('slug')).toHaveAccessibleDescription('Slug варианта занят');

    net.on('PATCH', `${ATTRIBUTES}/11/options/101`, {
      id: 101,
      slug: 'steel',
      sort_order: 1,
      values: { ru: 'Сталь оцинкованная' },
    });
    net.on('GET', `${ATTRIBUTES}/11`, materialAttribute());
    await user.clear(steel.getByLabelText('slug'));
    await user.type(steel.getByLabelText('slug'), 'steel');
    await user.type(steel.getByLabelText('Значение'), ' оцинкованная');
    await user.click(steel.getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(net.calls('PATCH', `${ATTRIBUTES}/11/options/101`)).toHaveLength(2));
    expect(bodyOf('PATCH', `${ATTRIBUTES}/11/options/101`, 1)).toEqual({
      values: { ru: 'Сталь оцинкованная' },
    });
    expect(await screen.findByText('Вариант сохранён')).toBeInTheDocument();
  });

  it('удаление: подтверждение; 409 «вариант выбран у товаров»', async () => {
    net.on(
      'DELETE',
      `${ATTRIBUTES}/11/options/100`,
      errorResponse(409, 'attribute_option_in_use', 'Вариант используется'),
    );
    const { user, drawer } = await openMaterial();
    await user.click(
      within(drawer).getByRole('button', { name: 'Удалить вариант «Полипропилен»' }),
    );
    const dialog = await screen.findByRole('dialog', { name: 'Удалить вариант «Полипропилен»?' });
    await user.click(within(dialog).getByRole('button', { name: 'Удалить' }));
    expect(
      await screen.findByText('Вариант выбран у товаров — сначала замените его в карточках'),
    ).toBeInTheDocument();

    net.on('DELETE', `${ATTRIBUTES}/11/options/101`, noContent);
    net.on(
      'GET',
      `${ATTRIBUTES}/11`,
      materialAttribute({ options: [materialAttribute().options![0]!] }),
    );
    await user.click(within(drawer).getByRole('button', { name: 'Удалить вариант «Сталь»' }));
    await user.click(
      within(await screen.findByRole('dialog', { name: 'Удалить вариант «Сталь»?' })).getByRole(
        'button',
        { name: 'Удалить' },
      ),
    );
    expect(await screen.findByText('Вариант удалён')).toBeInTheDocument();
    await waitFor(() =>
      expect(
        within(drawer).queryByRole('button', { name: 'Удалить вариант «Сталь»' }),
      ).not.toBeInTheDocument(),
    );
  });

  it('пустой новый вариант не отправляется', async () => {
    const { user, drawer } = await openMaterial();
    await user.click(within(drawer).getByRole('button', { name: 'Добавить' }));
    expect(within(drawer).getByLabelText('Новый вариант')).toHaveAttribute('aria-invalid', 'true');
    expect(net.calls('POST', `${ATTRIBUTES}/11/options`)).toHaveLength(0);
  });
});

// ================================================================ интеграция с товаром
describe('назначение характеристик и карточка товара', () => {
  it('назначенная категории характеристика появляется в товаре и её значение сохраняется', async () => {
    // Состояние «сервера»: у категории «Канаты» пока нет характеристик,
    // у товара заполнен диаметр — он виден как «не назначенный».
    let assigned: CategoryAttribute[] = [];
    const catalog = [makeAttribute(), materialAttribute(), colorAttribute()];
    const product = makeProduct({ attributes: [makeProduct().attributes![0]!] });

    net.on('GET', `${CATEGORIES}/2/attributes`, () => jsonResponse(assigned));
    net.on('PUT', `${CATEGORIES}/2/attributes`, (_url: URL, init: RequestInit) => {
      const { items } = JSON.parse(String(init.body)) as { items: CategoryAttributeItem[] };
      assigned = items.map((item) => {
        const attribute = catalog.find((entry) => entry.id === item.attribute_id)!;
        return {
          attribute_id: attribute.id,
          code: attribute.code,
          name: attribute.name,
          value_type: attribute.value_type,
          unit: attribute.unit,
          sort_order: item.sort_order ?? 0,
          is_required: item.is_required ?? false,
        };
      });
      return jsonResponse(assigned);
    });
    net.on('GET', `${ATTRIBUTES}/11`, materialAttribute());
    net.on('GET', PRODUCT_URL, product);
    net.on('PUT', `${PRODUCT_URL}/attributes`, product);

    // 1. Товар до назначения.
    signInAs(net, 'CONTENT_MANAGER');
    net.on('GET', TREE, CATEGORY_TREE);
    navigationState.search = 'tab=attributes';
    const first = renderInPanel(<ProductEditorScreen id={PRODUCT_ID} />);
    expect(await screen.findByText(/Не назначены категориям товара/)).toBeInTheDocument();
    first.unmount();

    // 2. Категории назначают диаметр и материал.
    resetSessionForTests();
    await openCategories({ search: 'id=2', category: makeCategory(), assigned: [] });
    net.on('GET', ATTRIBUTES, page(catalog));
    net.on('GET', `${CATEGORIES}/2/attributes`, () => jsonResponse(assigned));
    const user = userEvent.setup();
    const select = await screen.findByLabelText('Добавить характеристику');
    await waitFor(() => expect(select).toBeEnabled());
    await user.selectOptions(select, '10');
    await user.click(screen.getByRole('button', { name: 'Добавить' }));
    await user.selectOptions(screen.getByLabelText('Добавить характеристику'), '11');
    await user.click(screen.getByRole('button', { name: 'Добавить' }));
    await user.click(screen.getByRole('button', { name: 'Сохранить характеристики' }));
    expect(await screen.findByText('Характеристики категории сохранены')).toBeInTheDocument();
    expect(assigned.map((item) => item.attribute_id)).toEqual([10, 11]);
    cleanupRender();

    // 3. Товар после назначения: обе характеристики в группе категории.
    resetSessionForTests();
    signInAs(net, 'CONTENT_MANAGER');
    net.on('GET', TREE, CATEGORY_TREE);
    navigationState.pathname = '/products/5';
    navigationState.search = 'tab=attributes';
    renderInPanel(<ProductEditorScreen id={PRODUCT_ID} />);
    const diameter = await screen.findByLabelText(/Диаметр/);
    expect(diameter).toHaveValue('16');
    expect(screen.getByLabelText('Полипропилен')).not.toBeChecked();
    expect(screen.queryByText(/Не назначены категориям товара/)).not.toBeInTheDocument();

    await user.click(screen.getByLabelText('Сталь'));
    await user.clear(diameter);
    await user.type(diameter, '20');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(net.calls('PUT', `${PRODUCT_URL}/attributes`)).toHaveLength(1));
    expect(bodyOf('PUT', `${PRODUCT_URL}/attributes`)).toEqual({
      items: [
        { attribute_id: 10, value_numeric: '20' },
        { attribute_id: 11, option_id: 101 },
      ],
    });
  });
});

function cleanupRender() {
  document.body.innerHTML = '';
}
