/**
 * Раздел «Контент»: обзор разделов, загрузка и сохранение каждой формы,
 * проверки, ошибки backend (401/403/404/422), несохранённые изменения,
 * FAQ, медиа, SEO, казахская версия и права.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import ContentSectionPage from '@/app/(panel)/content/[section]/page';
import ContentPage from '@/app/(panel)/content/page';
import { AppProviders } from '@/components/AppProviders';
import { ContentOverview, ContentSectionScreen } from '@/components/content/ContentScreens';
import { AuthGate } from '@/components/session/AuthGate';
import type { ContentSectionKey, ContentSectionRead, UserRole } from '@/lib/api/types';
import { resetSessionForTests } from '@/lib/auth/session';
import { visibleNav } from '@/lib/navigation';

import {
  CONTENT,
  FAQ,
  HERO_IMAGE,
  HOME,
  makeMedia,
  makeRead,
  mediaRow,
  mediaUrl,
  MEDIA,
  OG_IMAGE,
  SECTION_DATA,
  sectionUrl,
  SETTINGS,
  SUMMARIES,
} from './content-fixtures';
import {
  createFetchMock,
  errorResponse,
  jsonResponse,
  makeUser,
  page,
  ROLE_PERMISSIONS,
  signInAs,
} from './helpers';
import { navigationState, routerPush, routerReplace } from './setup';

// Тесты запускаются из каталога приложения (pnpm --filter admin test).
const CSS_PATH = join(process.cwd(), 'src/components/content/Content.module.css');

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

async function openSection<K extends ContentSectionKey>(
  key: K,
  {
    role = 'CONTENT_MANAGER',
    read = makeRead(key),
  }: { role?: UserRole; read?: ContentSectionRead<K> } = {},
) {
  signInAs(net, role);
  navigationState.pathname = `/content/${key}`;
  net.on('GET', sectionUrl(key), read);
  net.on('GET', mediaUrl(OG_IMAGE), makeMedia());
  net.on(
    'GET',
    mediaUrl(HERO_IMAGE),
    makeMedia({ uuid: HERO_IMAGE, original_filename: 'hero.jpg', width: 1846, height: 852 }),
  );
  const user = userEvent.setup();
  renderInPanel(<ContentSectionScreen section={key} />);
  await screen.findByRole('button', { name: 'Сохранить' });
  return user;
}

/** Подпись обязательного поля: к тексту добавлена звёздочка. */
function req(label: string): RegExp {
  // В подписях полей нет спецсимволов регулярных выражений.
  return new RegExp(`^${label}\\*?$`);
}

function item(name: string) {
  return within(screen.getByRole('listitem', { name }));
}

beforeEach(() => {
  resetSessionForTests();
  net = createFetchMock();
  vi.stubGlobal('fetch', net.mock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ================================================================= обзор
describe('обзор разделов', () => {
  it('семь разделов: статус, дата изменения, редактирование и страница сайта', async () => {
    signInAs(net, 'CONTENT_MANAGER');
    net.on('GET', CONTENT, SUMMARIES);
    renderInPanel(<ContentOverview />);

    const list = await screen.findByRole('list', { name: 'Разделы контента' });
    await within(list).findAllByText('Заполнен');
    const cards = within(list).getAllByRole('listitem');
    expect(cards.map((card) => within(card).getByRole('heading').textContent)).toEqual([
      'Главная',
      'Контакты',
      'Доставка',
      'FAQ',
      'Реквизиты',
      'Настройки',
      'Услуги',
    ]);
    expect(list).toHaveAttribute('aria-busy', 'false');

    const faq = within(cards[3]!);
    expect(faq.getByText('Заполнен')).toBeInTheDocument();
    expect(faq.getByText('Изменён 12.09.2026, 11:00')).toBeInTheDocument();
    expect(faq.getByRole('link', { name: 'Редактировать' })).toHaveAttribute(
      'href',
      '/content/faq',
    );
    const site = faq.getByRole('link', { name: /Открыть страницу: FAQ/ });
    expect(site).toHaveAttribute('href', 'http://localhost:3000/faq');
    expect(site).toHaveAttribute('target', '_blank');

    const delivery = within(cards[2]!);
    expect(delivery.getByText('Не заполнен')).toBeInTheDocument();
    expect(delivery.getByText('Сайт показывает тексты по умолчанию')).toBeInTheDocument();
    expect(
      within(cards[4]!).getByRole('link', { name: /Открыть страницу: Реквизиты/ }),
    ).toHaveAttribute('href', 'http://localhost:3000/contacts#requisites');
  });

  it('загрузка — скелетон, ошибка — «Повторить»', async () => {
    signInAs(net, 'CONTENT_MANAGER');
    let fail = true;
    net.on('GET', CONTENT, () =>
      fail ? errorResponse(500, 'internal', 'Ошибка') : jsonResponse(SUMMARIES),
    );
    const user = userEvent.setup();
    renderInPanel(<ContentOverview />);

    expect(await screen.findByText('Не удалось загрузить данные')).toBeInTheDocument();
    fail = false;
    await user.click(screen.getByRole('button', { name: 'Повторить' }));
    const list = await screen.findByRole('list', { name: 'Разделы контента' });
    await within(list).findAllByText('Заполнен');
  });

  it('пока список грузится, карточки помечены как загружающиеся', async () => {
    signInAs(net, 'CONTENT_MANAGER');
    let release: (response: Response) => void = () => undefined;
    net.on('GET', CONTENT, () => new Promise<Response>((resolve) => (release = resolve)));
    renderInPanel(<ContentOverview />);

    const list = await screen.findByRole('list', { name: 'Разделы контента' });
    expect(list).toHaveAttribute('aria-busy', 'true');
    expect(within(list).queryByText('Заполнен')).not.toBeInTheDocument();
    await waitFor(() => expect(net.calls('GET', CONTENT)).toHaveLength(1));
    act(() => release(jsonResponse(SUMMARIES)));
    await waitFor(() => expect(list).toHaveAttribute('aria-busy', 'false'));
  });
});

// ======================================================== экран раздела
describe('экран раздела', () => {
  it.each([
    ['home', req('Заголовок'), 'Комплектующие для современных площадок'],
    ['contacts', 'Адрес', 'Алматы, ул. Складская, 1'],
    ['delivery', 'Вступление', 'Доставляем по всему Казахстану.'],
    ['faq', req('Вопрос'), 'Есть ли доставка?'],
    ['requisites', 'IBAN', 'KZ86125KZT5004100100'],
    ['settings', 'Название сайта', 'OINAU PRO'],
  ] as const)('%s: загрузка текущего контента в форму', async (key, label, value) => {
    await openSection(key);
    expect(net.calls('GET', sectionUrl(key))).toHaveLength(1);
    expect(screen.getAllByLabelText(label)[0]).toHaveValue(value);
    expect(screen.getByRole('button', { name: 'Сохранить' })).toBeDisabled();
    expect(screen.getByText('Изменений нет')).toBeInTheDocument();
    const title = screen.getByRole('heading', { level: 1 }).textContent ?? '';
    expect(
      within(screen.getByRole('navigation', { name: 'Разделы контента' })).getByRole('button', {
        name: title,
      }),
    ).toHaveAttribute('aria-current', 'page');
  });

  it('неизвестный раздел — понятный экран без запросов', async () => {
    signInAs(net, 'CONTENT_MANAGER');
    renderInPanel(<ContentSectionScreen section="pages" />);
    expect(await screen.findByText('Такого раздела контента нет')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Ко всем разделам' })).toHaveAttribute(
      'href',
      '/content',
    );
    expect(net.mock.mock.calls.some(([url]) => String(url).includes('/admin/content'))).toBe(false);
  });

  it('скелетон при загрузке, ошибка сервера и повтор', async () => {
    signInAs(net, 'CONTENT_MANAGER');
    let respond: () => Response = () => errorResponse(500, 'internal', 'Ошибка');
    let release: () => void = () => undefined;
    net.on(
      'GET',
      sectionUrl('faq'),
      () => new Promise<Response>((resolve) => (release = () => resolve(respond()))),
    );
    const user = userEvent.setup();
    renderInPanel(<ContentSectionScreen section="faq" />);

    expect(await screen.findByText('Загружаем раздел…')).toBeInTheDocument();
    await waitFor(() => expect(net.calls('GET', sectionUrl('faq'))).toHaveLength(1));
    act(() => release());
    expect(await screen.findByText('Не удалось загрузить данные')).toBeInTheDocument();
    expect(screen.getByText('Ошибка сервера. Код запроса: req-test')).toBeInTheDocument();

    respond = () => jsonResponse(makeRead('faq'));
    await user.click(screen.getByRole('button', { name: 'Повторить' }));
    await waitFor(() => expect(net.calls('GET', sectionUrl('faq'))).toHaveLength(2));
    act(() => release());
    expect(await screen.findByRole('button', { name: 'Сохранить' })).toBeInTheDocument();
  });

  it('раздел ещё не сохранялся: пустая форма и пояснение', async () => {
    await openSection('faq', {
      read: makeRead('faq', { items: [], seo: {} }, { is_configured: false, updated_at: null }),
    });
    expect(screen.getByText('Ещё не сохранялся')).toBeInTheDocument();
    expect(screen.getByText('Сайт показывает тексты по умолчанию')).toBeInTheDocument();
    expect(screen.getByText('Вопросов пока нет')).toBeInTheDocument();
  });

  it('ссылка «Открыть страницу» ведёт на публичную страницу раздела', async () => {
    await openSection('delivery');
    const link = screen.getByRole('link', { name: /Открыть страницу: Доставка/ });
    expect(link).toHaveAttribute('href', 'http://localhost:3000/delivery');
    expect(link).toHaveAttribute('rel', 'noreferrer');
  });
});

// ============================================================ сохранение
describe('редактирование и сохранение', () => {
  it('правка → PUT всего раздела по схеме → toast, изменений больше нет', async () => {
    const user = await openSection('faq');
    const saved = { ...FAQ, items: [FAQ.items![0]!, { ...FAQ.items![1]!, answer: { ru: 'Да.' } }] };
    net.on('PUT', sectionUrl('faq'), makeRead('faq', saved));

    const answer = item('Вопрос 2').getByLabelText(req('Ответ'));
    await user.clear(answer);
    await user.type(answer, '  Да.  ');
    expect(screen.getByText('Есть несохранённые изменения')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));

    expect(await screen.findByText('Раздел «FAQ» сохранён')).toBeInTheDocument();
    expect(bodyOf('PUT', sectionUrl('faq'))).toEqual(saved);
    expect(screen.getByText('Изменений нет')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Сохранить' })).toBeDisabled();
    expect(item('Вопрос 2').getByLabelText(req('Ответ'))).toHaveValue('Да.');
  });

  it('кнопка сохранения показывает процесс и блокирует форму', async () => {
    const user = await openSection('settings');
    let release: () => void = () => undefined;
    net.on(
      'PUT',
      sectionUrl('settings'),
      () =>
        new Promise<Response>((resolve) => {
          release = () => resolve(jsonResponse(makeRead('settings')));
        }),
    );
    await user.type(screen.getByLabelText('Название сайта'), '!');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Сохранить' })).toHaveAttribute(
        'aria-busy',
        'true',
      ),
    );
    expect(screen.getByLabelText('Название сайта')).toBeDisabled();
    act(() => release());
    expect(await screen.findByText('Раздел «Настройки» сохранён')).toBeInTheDocument();
  });

  it('«Отменить» спрашивает подтверждение и возвращает сохранённые значения', async () => {
    const user = await openSection('delivery');
    const intro = screen.getByLabelText('Вступление');
    await user.clear(intro);
    await user.type(intro, 'Новый текст');

    await user.click(screen.getByRole('button', { name: 'Отменить' }));
    let dialog = await screen.findByRole('dialog', { name: 'Отменить изменения?' });
    await user.click(within(dialog).getByRole('button', { name: 'Продолжить редактирование' }));
    expect(intro).toHaveValue('Новый текст');

    await user.click(screen.getByRole('button', { name: 'Отменить' }));
    dialog = await screen.findByRole('dialog', { name: 'Отменить изменения?' });
    await user.click(within(dialog).getByRole('button', { name: 'Сбросить' }));
    expect(screen.getByLabelText('Вступление')).toHaveValue('Доставляем по всему Казахстану.');
    expect(screen.getByRole('button', { name: 'Сохранить' })).toBeDisabled();
    expect(net.calls('PUT', sectionUrl('delivery'))).toHaveLength(0);
  });

  it('проверка формы: RU обязателен, без HTML — запрос не уходит, фокус на ошибке', async () => {
    const user = await openSection('faq');
    await user.clear(item('Вопрос 1').getByLabelText(req('Вопрос')));
    const answer = item('Вопрос 2').getByLabelText(req('Ответ'));
    await user.clear(answer);
    await user.type(answer, 'Смотрите <a href="x">тут</a>');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));

    expect(
      await screen.findByText('Раздел не сохранён: проверьте отмеченные поля (2).'),
    ).toBeInTheDocument();
    expect(item('Вопрос 1').getByText('Заполните текст на русском')).toBeInTheDocument();
    expect(
      item('Вопрос 2').getByText('HTML-разметка не допускается: поле хранит простой текст'),
    ).toBeInTheDocument();
    await waitFor(() => expect(item('Вопрос 1').getByLabelText(req('Вопрос'))).toHaveFocus());
    expect(net.calls('PUT', sectionUrl('faq'))).toHaveLength(0);

    // Правка поля снимает его ошибку.
    await user.type(item('Вопрос 1').getByLabelText(req('Вопрос')), 'Сроки?');
    expect(item('Вопрос 1').queryByText('Заполните текст на русском')).not.toBeInTheDocument();
  });

  it('422 backend раскладывается по полям; ошибка без поля — в сводке, SEO раскрывается', async () => {
    const user = await openSection('faq');
    net.on(
      'PUT',
      sectionUrl('faq'),
      errorResponse(422, 'validation_error', 'Ошибка валидации', {
        fields: [
          { loc: ['body', 'items', 1, 'answer'], msg: 'Value error, Текст длиннее 5000 символов' },
          { loc: ['body', 'seo', 'title'], msg: 'Value error, Обязателен текст для локали ru' },
          { loc: ['body', 'seo', 'robots'], msg: 'Extra inputs are not permitted' },
        ],
      }),
    );
    const seoToggle = screen.getByRole('button', { name: /^SEO/ });
    expect(seoToggle).toHaveAttribute('aria-expanded', 'false');

    await user.type(item('Вопрос 2').getByLabelText(req('Ответ')), '!');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));

    expect(await item('Вопрос 2').findByText('Текст длиннее 5000 символов')).toBeInTheDocument();
    expect(seoToggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByLabelText('Заголовок (title)')).toHaveAccessibleDescription(
      'Обязателен текст для локали ru',
    );
    const alert = screen.getByText(
      /Раздел не сохранён: проверьте отмеченные поля \(3\)/,
    ).parentElement!;
    expect(
      within(alert).getByText('seo.robots: Extra inputs are not permitted'),
    ).toBeInTheDocument();
    expect(screen.getByText('Раздел не сохранён')).toBeInTheDocument();
    // Черновик не потерян.
    expect(screen.getByText('Есть несохранённые изменения')).toBeInTheDocument();
  });

  it('403 при сохранении: понятный toast, правки остаются', async () => {
    const user = await openSection('requisites');
    net.on('PUT', sectionUrl('requisites'), errorResponse(403, 'permission_denied', 'Нет прав'));
    await user.type(screen.getByLabelText('Наименование'), ' Плюс');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));

    expect(await screen.findByText('Нет права изменять контент')).toBeInTheDocument();
    expect(screen.getByText('Недостаточно прав для этого действия.')).toBeInTheDocument();
    expect(screen.getByLabelText('Наименование')).toHaveValue('ТОО «OINAU PRO» Плюс');
    expect(screen.getByText('Есть несохранённые изменения')).toBeInTheDocument();
  });

  it('401 при загрузке — переход на вход с возвратом в раздел', async () => {
    navigationState.pathname = '/content/faq';
    window.localStorage.setItem('oinau.admin.session', '1');
    net.on('POST', '/api/v1/admin/auth/refresh', errorResponse(401, 'unauthenticated', 'x'));
    renderInPanel(<ContentSectionScreen section="faq" />);
    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith('/login?next=%2Fcontent%2Ffaq'));
    expect(net.calls('GET', sectionUrl('faq'))).toHaveLength(0);
  });

  it('403 при загрузке — экран «Нет доступа»', async () => {
    signInAs(net, 'CONTENT_MANAGER');
    net.on('GET', sectionUrl('home'), errorResponse(403, 'permission_denied', 'Нет прав'));
    renderInPanel(<ContentSectionScreen section="home" />);
    expect(await screen.findByText('Нет доступа')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Сохранить' })).not.toBeInTheDocument();
  });
});

// ================================================== несохранённые изменения
describe('несохранённые изменения', () => {
  it('переход в другой раздел спрашивает подтверждение', async () => {
    const user = await openSection('faq');
    // Без изменений — сразу.
    await user.click(screen.getByRole('button', { name: 'Доставка' }));
    expect(routerPush).toHaveBeenLastCalledWith('/content/delivery');
    routerPush.mockClear();

    await user.type(item('Вопрос 1').getByLabelText(req('Вопрос')), ' Точно?');
    await user.click(screen.getByRole('button', { name: 'Контакты' }));
    let dialog = await screen.findByRole('dialog', { name: 'Уйти без сохранения?' });
    await user.click(within(dialog).getByRole('button', { name: 'Остаться' }));
    expect(routerPush).not.toHaveBeenCalled();
    expect(item('Вопрос 1').getByLabelText(req('Вопрос'))).toHaveValue('Есть ли доставка? Точно?');

    await user.click(screen.getByRole('button', { name: 'Контакты' }));
    dialog = await screen.findByRole('dialog', { name: 'Уйти без сохранения?' });
    await user.click(within(dialog).getByRole('button', { name: 'Не сохранять' }));
    expect(routerPush).toHaveBeenCalledWith('/content/contacts');
  });

  it('клик по внутренней ссылке (крошки, меню) перехватывается', async () => {
    const user = await openSection('settings');
    await user.type(screen.getByLabelText('Название сайта'), '!');

    await user.click(screen.getByRole('link', { name: 'Контент' }));
    const dialog = await screen.findByRole('dialog', { name: 'Уйти без сохранения?' });
    expect(routerPush).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole('button', { name: 'Не сохранять' }));
    expect(routerPush).toHaveBeenCalledWith('/content');
  });

  it('внешняя ссылка в новой вкладке не перехватывается', async () => {
    const user = await openSection('faq');
    await user.type(item('Вопрос 1').getByLabelText(req('Вопрос')), '!');
    const link = screen.getByRole('link', { name: /Открыть страницу: FAQ/ });
    link.addEventListener('click', (event) => event.preventDefault());
    await user.click(link);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('закрытие вкладки при изменениях предупреждает, после сохранения — нет', async () => {
    const user = await openSection('faq');
    const unload = () => {
      const event = new Event('beforeunload', { cancelable: true });
      window.dispatchEvent(event);
      return event.defaultPrevented;
    };
    expect(unload()).toBe(false);
    await user.type(item('Вопрос 1').getByLabelText(req('Вопрос')), '!');
    expect(unload()).toBe(true);

    net.on('PUT', sectionUrl('faq'), (_url: URL, init: RequestInit) =>
      jsonResponse(makeRead('faq', JSON.parse(String(init.body)))),
    );
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    await screen.findByText('Раздел «FAQ» сохранён');
    await waitFor(() => expect(unload()).toBe(false));
    expect(screen.getByText('Изменений нет')).toBeInTheDocument();
  });
});

// =================================================================== FAQ
describe('FAQ', () => {
  it('добавление, порядок, удаление с подтверждением — порядок уходит в PUT', async () => {
    const user = await openSection('faq');
    net.on('PUT', sectionUrl('faq'), (_url: URL, init: RequestInit) =>
      jsonResponse(makeRead('faq', JSON.parse(String(init.body)))),
    );

    await user.click(screen.getByRole('button', { name: 'Добавить вопрос' }));
    const added = item('Вопрос 3');
    await waitFor(() => expect(added.getByLabelText(req('Вопрос'))).toHaveFocus());
    await user.type(added.getByLabelText(req('Вопрос')), 'Есть ли гарантия?');
    await user.type(added.getByLabelText(req('Ответ')), 'Да, 12 месяцев.');

    await user.click(screen.getByRole('button', { name: 'Выше: Вопрос 3' }));
    expect(item('Вопрос 2').getByLabelText(req('Вопрос'))).toHaveValue('Есть ли гарантия?');
    expect(screen.getByRole('button', { name: 'Выше: Вопрос 1' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Ниже: Вопрос 3' })).toBeDisabled();

    await user.click(screen.getByRole('button', { name: 'Удалить: Вопрос 1' }));
    const dialog = await screen.findByRole('dialog', { name: 'Удалить «Есть ли доставка?»?' });
    await user.click(within(dialog).getByRole('button', { name: 'Удалить' }));
    expect(screen.getAllByRole('listitem', { name: /^Вопрос \d$/ })).toHaveLength(2);

    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    await screen.findByText('Раздел «FAQ» сохранён');
    expect(bodyOf('PUT', sectionUrl('faq'))).toEqual({
      items: [
        { question: { ru: 'Есть ли гарантия?' }, answer: { ru: 'Да, 12 месяцев.' } },
        FAQ.items![1],
      ],
      seo: FAQ.seo,
    });
  });

  it('пустой новый вопрос удаляется без подтверждения; счётчик и предел', async () => {
    const user = await openSection('faq');
    await user.click(screen.getByRole('button', { name: 'Добавить вопрос' }));
    // Счётчик — в заголовке панели и под списком.
    expect(screen.getAllByText('3 из 100')).toHaveLength(2);
    await user.click(screen.getByRole('button', { name: 'Удалить: Вопрос 3' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getAllByText('2 из 100')).toHaveLength(2);
    // Вернулись к исходному — изменений нет.
    expect(screen.getByRole('button', { name: 'Сохранить' })).toBeDisabled();
  });

  it('отмена удаления оставляет вопрос', async () => {
    const user = await openSection('faq');
    await user.click(screen.getByRole('button', { name: 'Удалить: Вопрос 2' }));
    const dialog = await screen.findByRole('dialog', { name: 'Удалить «Работаете с ТОО?»?' });
    await user.click(within(dialog).getByRole('button', { name: 'Отмена' }));
    expect(screen.getAllByRole('listitem', { name: /^Вопрос \d$/ })).toHaveLength(2);
  });

  it('предпросмотр показывает вопросы в порядке сайта, текст — как простой текст', async () => {
    const user = await openSection('faq');
    await user.type(item('Вопрос 1').getByLabelText(req('Ответ')), '\nВторой абзац');
    await user.click(screen.getByRole('button', { name: 'Предпросмотр' }));

    const preview = screen.getByLabelText('Предпросмотр FAQ');
    const questions = within(preview).getAllByRole('group');
    expect(questions.map((node) => node.querySelector('summary')?.textContent)).toEqual([
      'Есть ли доставка?',
      'Работаете с ТОО?',
    ]);
    expect(
      within(preview).getByText(/Да, по всему Казахстану\.\s+Второй абзац/),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Вернуться к редактированию' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  it('пустой FAQ: состояние и добавление первого вопроса', async () => {
    const user = await openSection('faq', { read: makeRead('faq', { items: [], seo: {} }) });
    expect(screen.getByText('Страница FAQ на сайте будет пустой.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Добавить вопрос' }));
    expect(screen.getByRole('listitem', { name: 'Вопрос 1' })).toBeInTheDocument();
  });
});

// ===================================================== локализация (KK)
describe('казахская версия', () => {
  it('поля KK по переключателю; перевод уходит в PUT рядом с RU', async () => {
    const user = await openSection('faq');
    net.on('PUT', sectionUrl('faq'), (_url: URL, init: RequestInit) =>
      jsonResponse(makeRead('faq', JSON.parse(String(init.body)))),
    );
    expect(screen.queryByLabelText('Вопрос · KK')).not.toBeInTheDocument();
    await user.click(screen.getByRole('switch', { name: /Казахская версия/ }));

    await user.type(item('Вопрос 1').getByLabelText('Вопрос · KK'), 'Жеткізу бар ма?');
    await user.type(item('Вопрос 1').getByLabelText('Ответ · KK'), 'Иә.');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    await screen.findByText('Раздел «FAQ» сохранён');

    const body = bodyOf('PUT', sectionUrl('faq')) as typeof FAQ;
    expect(body.items?.[0]).toEqual({
      question: { ru: 'Есть ли доставка?', kk: 'Жеткізу бар ма?' },
      answer: { ru: 'Да, по всему Казахстану.', kk: 'Иә.' },
    });
  });

  it('перевод без русской версии не сохраняется; KK включён, если он уже заполнен', async () => {
    const withKk = {
      ...FAQ,
      items: [{ question: { ru: 'Вопрос', kk: 'Сұрақ' }, answer: { ru: 'Ответ' } }],
    };
    const user = await openSection('faq', { read: makeRead('faq', withKk) });
    expect(screen.getByRole('switch', { name: /Казахская версия/ })).toBeChecked();
    expect(item('Вопрос 1').getByLabelText('Вопрос · KK')).toHaveValue('Сұрақ');

    await user.clear(item('Вопрос 1').getByLabelText(req('Вопрос · RU')));
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findByText('Заполните текст на русском')).toBeInTheDocument();
    expect(net.calls('PUT', sectionUrl('faq'))).toHaveLength(0);
  });
});

// ================================================================ главная
describe('главная', () => {
  it('hero, акцент заголовка, преимущества, SEO свёрнут', async () => {
    await openSection('home');
    expect(screen.getByLabelText('Подзаголовок')).toHaveValue(
      'Канаты, крепёж и сиденья со склада в Алматы',
    );
    expect(screen.getByLabelText('Ссылка кнопки')).toHaveValue('/catalog');
    const accent = screen.getByLabelText('Как выделится заголовок');
    expect(within(accent).getByText('современных').tagName).toBe('MARK');
    expect(screen.getAllByRole('listitem', { name: /^Преимущество/ })).toHaveLength(2);

    const seo = screen.getByRole('button', { name: /^SEO/ });
    expect(seo).toHaveAttribute('aria-expanded', 'false');
    expect(seo).toHaveTextContent('Заполнено 2 из 5');
  });

  it('кнопка: текст без ссылки не сохраняется; пустые поля уходят как null', async () => {
    const user = await openSection('home');
    net.on('PUT', sectionUrl('home'), (_url: URL, init: RequestInit) =>
      jsonResponse(makeRead('home', JSON.parse(String(init.body)))),
    );
    await user.clear(screen.getByLabelText('Ссылка кнопки'));
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findByText('Текст и ссылка кнопки задаются вместе')).toBeInTheDocument();
    expect(net.calls('PUT', sectionUrl('home'))).toHaveLength(0);

    await user.clear(screen.getAllByLabelText('Текст кнопки')[0]!);
    await user.clear(item('Преимущество 1').getByLabelText('Текст'));
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    await screen.findByText('Раздел «Главная» сохранён');

    const body = bodyOf('PUT', sectionUrl('home')) as typeof HOME;
    expect(body.hero).toEqual({ ...HOME.hero, cta_label: null, cta_url: null });
    expect(body.advantages?.[0]).toEqual({ title: { ru: 'Склад в Алматы' }, text: null });
    expect(body.about).toEqual(HOME.about);
    expect(body.seo).toEqual(HOME.seo);
  });

  it('SEO-поля редактируются и сохраняются', async () => {
    const user = await openSection('home');
    net.on('PUT', sectionUrl('home'), (_url: URL, init: RequestInit) =>
      jsonResponse(makeRead('home', JSON.parse(String(init.body)))),
    );
    await user.click(screen.getByRole('button', { name: /^SEO/ }));
    await user.type(
      screen.getByLabelText('Описание (description)'),
      'Канаты и крепёж для детских площадок',
    );
    await user.type(screen.getByLabelText('Заголовок для соцсетей (og:title)'), 'OINAU PRO');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    await screen.findByText('Раздел «Главная» сохранён');

    expect((bodyOf('PUT', sectionUrl('home')) as typeof HOME).seo).toEqual({
      title: { ru: 'OINAU PRO — главная' },
      description: { ru: 'Канаты и крепёж для детских площадок' },
      og_title: { ru: 'OINAU PRO' },
      og_description: null,
      og_image: OG_IMAGE,
    });
  });
});

// ================================================================== медиа
class FakeXHR {
  static requests: { method: string; url: string; body: unknown }[] = [];
  upload: {
    onprogress:
      ((event: { lengthComputable: boolean; loaded: number; total: number }) => void) | null;
  } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  status = 0;
  private method = '';
  private url = '';
  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }
  setRequestHeader() {}
  send(body: unknown) {
    FakeXHR.requests.push({ method: this.method, url: this.url, body });
    setTimeout(() => {
      this.upload.onprogress?.({ lengthComputable: true, loaded: 1, total: 1 });
      this.status = 200;
      this.onload?.();
    }, 0);
  }
  abort() {
    this.onabort?.();
  }
}

describe('медиа', () => {
  const NEW_UUID = '33333333-3333-4333-8333-333333333333';

  function heroMedia() {
    return within(screen.getByRole('group', { name: 'Изображение первого экрана' }));
  }

  it('превью по ссылке варианта, «Убрать» снимает ссылку, файл не удаляется', async () => {
    const user = await openSection('home');
    net.on('PUT', sectionUrl('home'), (_url: URL, init: RequestInit) =>
      jsonResponse(makeRead('home', JSON.parse(String(init.body)))),
    );
    const preview = await heroMedia().findByRole('img', { name: 'Превью: hero.jpg' });
    expect(preview).toHaveAttribute(
      'src',
      `http://cdn.test/content/${HERO_IMAGE}/variants/thumb.webp`,
    );
    expect(heroMedia().getByText('1846×852')).toBeInTheDocument();
    expect(heroMedia().getByText('Готово')).toBeInTheDocument();

    await user.click(heroMedia().getByRole('button', { name: 'Убрать' }));
    expect(heroMedia().getByText('Изображение не выбрано')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    await screen.findByText('Раздел «Главная» сохранён');

    expect((bodyOf('PUT', sectionUrl('home')) as typeof HOME).hero?.image).toBeNull();
    expect(net.mock.mock.calls.some(([, init]) => (init as RequestInit).method === 'DELETE')).toBe(
      false,
    );
  });

  it('загрузка: intent (CONTENT) → PUT в хранилище → complete → опрос до READY → UUID в разделе', async () => {
    FakeXHR.requests = [];
    vi.stubGlobal('XMLHttpRequest', FakeXHR);
    const user = await openSection('home');
    net.on(
      'POST',
      `${MEDIA}/upload-intent`,
      jsonResponse(
        {
          media: mediaRow({ uuid: NEW_UUID, status: 'PENDING', url: null, variants: {} }),
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
      `${mediaUrl(NEW_UUID)}/complete`,
      jsonResponse(
        mediaRow({ uuid: NEW_UUID, status: 'PROCESSING', url: null, variants: {} }),
        202,
      ),
    );
    let polls = 0;
    net.on('GET', mediaUrl(NEW_UUID), () => {
      polls += 1;
      return jsonResponse(
        polls < 2
          ? makeMedia({ uuid: NEW_UUID, status: 'PROCESSING', url: null, variants: {} })
          : makeMedia({ uuid: NEW_UUID, original_filename: 'banner.png' }),
      );
    });
    net.on('PUT', sectionUrl('home'), (_url: URL, init: RequestInit) =>
      jsonResponse(makeRead('home', JSON.parse(String(init.body)))),
    );

    const file = new File(['png'], 'banner.png', { type: 'image/png' });
    await user.upload(screen.getByLabelText('Файл: Изображение первого экрана'), file);

    expect(
      await heroMedia().findByText('Файл обрабатывается — превью появится автоматически'),
    ).toBeInTheDocument();
    expect(bodyOf('POST', `${MEDIA}/upload-intent`)).toEqual({
      filename: 'banner.png',
      content_type: 'image/png',
      size_bytes: 3,
      purpose: 'CONTENT',
    });
    expect(FakeXHR.requests).toEqual([
      { method: 'PUT', url: 'http://storage.test/bucket/content/x/original.png?sig=1', body: file },
    ]);
    expect(
      await heroMedia().findByRole('img', { name: 'Превью: banner.png' }, { timeout: 4000 }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    await screen.findByText('Раздел «Главная» сохранён');
    expect((bodyOf('PUT', sectionUrl('home')) as typeof HOME).hero?.image).toBe(NEW_UUID);
  });

  it('выбор из медиатеки: только READY, поиск, UUID в разделе', async () => {
    const user = await openSection('home');
    net.on('GET', MEDIA, (url: URL) =>
      jsonResponse(
        page(
          url.searchParams.get('search') === 'nothing'
            ? []
            : [mediaRow({ uuid: NEW_UUID, original_filename: 'playground.jpg' })],
        ),
      ),
    );
    net.on(
      'GET',
      mediaUrl(NEW_UUID),
      makeMedia({ uuid: NEW_UUID, original_filename: 'playground.jpg' }),
    );
    net.on('PUT', sectionUrl('home'), (_url: URL, init: RequestInit) =>
      jsonResponse(makeRead('home', JSON.parse(String(init.body)))),
    );

    await user.click(heroMedia().getByRole('button', { name: 'Из медиатеки' }));
    const dialog = await screen.findByRole('dialog', { name: 'Медиатека' });
    await user.type(within(dialog).getByLabelText('Поиск по имени файла'), 'nothing');
    expect(await within(dialog).findByText('Ничего не найдено')).toBeInTheDocument();
    await user.clear(within(dialog).getByLabelText('Поиск по имени файла'));
    await user.click(await within(dialog).findByRole('button', { name: 'Выбрать playground.jpg' }));

    expect(screen.queryByRole('dialog', { name: 'Медиатека' })).not.toBeInTheDocument();
    expect(
      await heroMedia().findByRole('img', { name: 'Превью: playground.jpg' }),
    ).toBeInTheDocument();
    const params = new URL(String(net.calls('GET', MEDIA)[0]?.[0])).searchParams;
    expect(params.get('status')).toBe('READY');

    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    await screen.findByText('Раздел «Главная» сохранён');
    expect((bodyOf('PUT', sectionUrl('home')) as typeof HOME).hero?.image).toBe(NEW_UUID);
  });

  it('файл пропал из медиатеки: 404 превью и 404 при сохранении — у поля', async () => {
    signInAs(net, 'CONTENT_MANAGER');
    net.on('GET', sectionUrl('home'), makeRead('home'));
    net.on('GET', mediaUrl(HERO_IMAGE), makeMedia({ uuid: HERO_IMAGE }));
    net.on('GET', mediaUrl(OG_IMAGE), errorResponse(404, 'media_not_found', 'Файл не найден'));
    net.on(
      'PUT',
      sectionUrl('home'),
      errorResponse(404, 'media_not_found', 'Файл медиатеки не найден', {
        media_uuids: [OG_IMAGE],
      }),
    );
    const user = userEvent.setup();
    renderInPanel(<ContentSectionScreen section="home" />);
    await screen.findByRole('button', { name: 'Сохранить' });

    await user.type(screen.getByLabelText('Подзаголовок'), '!');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));

    const og = within(
      await screen.findByRole('group', { name: 'Изображение для соцсетей (og:image)' }),
    );
    expect(
      await og.findByText('Файл не найден в медиатеке — выберите другое изображение'),
    ).toBeVisible();
    expect(og.getByText('Файл не найден в медиатеке')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^SEO/ })).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Раздел не сохранён')).toBeInTheDocument();
  });

  it('без права загрузки и чтения каталога кнопок загрузки и медиатеки нет', async () => {
    window.localStorage.setItem('oinau.admin.session', '1');
    net.on('POST', '/api/v1/admin/auth/refresh', {
      access_token: 'a',
      token_type: 'bearer',
      expires_in: 900,
    });
    net.on(
      'GET',
      '/api/v1/admin/auth/me',
      makeUser('CONTENT_MANAGER', { permissions: ['content.write'] }),
    );
    net.on('GET', sectionUrl('home'), makeRead('home'));
    net.on('GET', mediaUrl(HERO_IMAGE), makeMedia({ uuid: HERO_IMAGE }));
    net.on('GET', mediaUrl(OG_IMAGE), makeMedia());
    renderInPanel(<ContentSectionScreen section="home" />);
    await screen.findByRole('button', { name: 'Сохранить' });

    expect(heroMedia().queryByRole('button', { name: 'Заменить' })).not.toBeInTheDocument();
    expect(heroMedia().queryByRole('button', { name: 'Из медиатеки' })).not.toBeInTheDocument();
    expect(heroMedia().getByRole('button', { name: 'Убрать' })).toBeInTheDocument();
  });
});

// ================================================= контакты, реквизиты, настройки
describe('контакты, реквизиты, настройки', () => {
  it('контакты: новый телефон и точка на карте проверяются, затем сохраняются', async () => {
    const user = await openSection('contacts');
    net.on('PUT', sectionUrl('contacts'), (_url: URL, init: RequestInit) =>
      jsonResponse(makeRead('contacts', JSON.parse(String(init.body)))),
    );
    await user.click(screen.getByRole('button', { name: 'Добавить телефон' }));
    await user.type(item('Телефон 2').getByLabelText(req('Номер')), '+7 abc');
    await user.click(screen.getByRole('button', { name: /^Точка на карте/ }));
    await user.clear(screen.getByLabelText('Долгота'));
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));

    expect(
      await item('Телефон 2').findByText(
        'Телефон может содержать только цифры, пробелы, «+», «-» и скобки',
      ),
    ).toBeInTheDocument();
    expect(screen.getByText('Укажите долготу вместе с широтой')).toBeInTheDocument();

    await user.clear(item('Телефон 2').getByLabelText(req('Номер')));
    await user.type(item('Телефон 2').getByLabelText(req('Номер')), '+7 701 111 22 33');
    await user.type(screen.getByLabelText('Долгота'), '76,95');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    await screen.findByText('Раздел «Контакты» сохранён');

    const body = bodyOf('PUT', sectionUrl('contacts')) as typeof SECTION_DATA.contacts;
    expect(body.phones).toEqual([
      { number: '+7 727 355 00 00', label: { ru: 'Отдел продаж' } },
      { number: '+7 701 111 22 33', label: null },
    ]);
    expect(body.map).toEqual({ latitude: 43.238949, longitude: 76.95 });
  });

  it('реквизиты: неверный IBAN не уходит на backend', async () => {
    const user = await openSection('requisites');
    const iban = screen.getByLabelText('IBAN');
    await user.clear(iban);
    await user.type(iban, 'KZ87125KZT5004100100');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findByText('Неверная контрольная сумма IBAN')).toBeInTheDocument();
    expect(net.calls('PUT', sectionUrl('requisites'))).toHaveLength(0);
  });

  it('настройки: соцсеть один раз и только https; телефоны — ссылка на «Контакты»', async () => {
    const user = await openSection('settings');
    expect(screen.getByRole('link', { name: '«Контакты»' })).toHaveAttribute(
      'href',
      '/content/contacts',
    );
    await user.click(screen.getByRole('button', { name: 'Добавить соцсеть' }));
    await user.selectOptions(item('Ссылка 2').getByLabelText(req('Соцсеть')), 'INSTAGRAM');
    await user.type(item('Ссылка 2').getByLabelText(req('Ссылка')), 'http://instagram.com/x');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));

    expect(
      await item('Ссылка 2').findByText('Каждая соцсеть указывается один раз'),
    ).toBeInTheDocument();
    expect(item('Ссылка 2').getByText('Допустимы только ссылки https://')).toBeInTheDocument();

    net.on('PUT', sectionUrl('settings'), (_url: URL, init: RequestInit) =>
      jsonResponse(makeRead('settings', JSON.parse(String(init.body)))),
    );
    await user.selectOptions(item('Ссылка 2').getByLabelText(req('Соцсеть')), 'TELEGRAM');
    await user.clear(item('Ссылка 2').getByLabelText(req('Ссылка')));
    await user.type(item('Ссылка 2').getByLabelText(req('Ссылка')), 'https://t.me/oinau');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    await screen.findByText('Раздел «Настройки» сохранён');
    expect((bodyOf('PUT', sectionUrl('settings')) as typeof SETTINGS).social_links).toEqual([
      SETTINGS.social_links![0],
      { network: 'TELEGRAM', url: 'https://t.me/oinau' },
    ]);
  });
});

// ================================================================== права
describe('права', () => {
  it.each(['MANAGER', 'VIEWER'] as const)(
    '%s: пункта меню нет, страницы — «Нет доступа», запросов к CMS нет',
    async (role) => {
      expect(
        visibleNav(new Set(ROLE_PERMISSIONS[role]))
          .flatMap((group) => group.items)
          .some((navItem) => navItem.href === '/content'),
      ).toBe(false);

      signInAs(net, role);
      const view = renderInPanel(<ContentPage />);
      expect(await screen.findByText('Нет доступа')).toBeInTheDocument();
      view.unmount();

      renderInPanel(await ContentSectionPage({ params: Promise.resolve({ section: 'faq' }) }));
      expect(await screen.findByText('Нет доступа')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Сохранить' })).not.toBeInTheDocument();
      expect(
        net.mock.mock.calls.some(([url]) => String(url).includes('/api/v1/admin/content')),
      ).toBe(false);
    },
  );

  it.each(['CONTENT_MANAGER', 'ADMIN', 'SUPERADMIN'] as const)(
    '%s: раздел в меню и форма с сохранением',
    async (role) => {
      expect(
        visibleNav(new Set(ROLE_PERMISSIONS[role]))
          .flatMap((group) => group.items)
          .some((navItem) => navItem.href === '/content'),
      ).toBe(true);
      signInAs(net, role);
      net.on('GET', sectionUrl('requisites'), makeRead('requisites'));
      renderInPanel(
        await ContentSectionPage({ params: Promise.resolve({ section: 'requisites' }) }),
      );
      expect(await screen.findByRole('button', { name: 'Сохранить' })).toBeInTheDocument();
      expect(screen.getByLabelText('Наименование')).toBeEnabled();
    },
  );
});

// ============================================================== адаптив
describe('адаптив', () => {
  it('вкладки разделов прокручиваются к активной', async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    await openSection('settings');
    expect(scroll).toHaveBeenCalledWith({ block: 'nearest', inline: 'nearest' });
    expect(screen.getByRole('navigation', { name: 'Разделы контента' })).toBeInTheDocument();
  });

  it('стили: вкладки прокручиваются внутри себя, узкий экран — одна колонка', () => {
    const css = readFileSync(CSS_PATH, 'utf8');
    const block = (selector: string, from = 0) => {
      const start = css.indexOf(`${selector} {`, from);
      return css.slice(start, css.indexOf('}', start));
    };
    expect(block('.tabs')).toContain('overflow-x: auto');
    // Свёрнутая панель: display: flex не должен перебивать атрибут hidden.
    expect(block('.panelBody[hidden]')).toContain('display: none');
    const tablet = css.indexOf('@media (max-width: 1024px)');
    const phone = css.indexOf('@media (max-width: 560px)');
    expect(tablet).toBeGreaterThan(0);
    expect(block('.grid2', tablet)).toContain('grid-template-columns: minmax(0, 1fr)');
    expect(block('.media', phone)).toContain('flex-direction: column');
    expect(block('.mediaPreview', phone)).toContain('width: 100%');
    // Ничего фиксированной ширины шире телефона.
    expect(css).not.toMatch(/min-width:\s*(4\d\d|[5-9]\d\d|\d{4})px/);
  });

  it('длинные подписи в списках обрезаются, а не раздвигают страницу', () => {
    const css = readFileSync(CSS_PATH, 'utf8');
    const summary = css.slice(
      css.indexOf('.listSummary {'),
      css.indexOf('}', css.indexOf('.listSummary {')),
    );
    expect(summary).toContain('min-width: 0');
    expect(summary).toContain('text-overflow: ellipsis');
  });
});

describe('услуги', () => {
  it('добавление услуги с пунктами «Что делаем» — всё уходит в PUT', async () => {
    const user = await openSection('services');
    net.on('PUT', sectionUrl('services'), (_url: URL, init: RequestInit) =>
      jsonResponse(makeRead('services', JSON.parse(String(init.body)))),
    );

    expect(item('Услуга 1').getByLabelText(req('Название'))).toHaveValue('Обжимка канатов');
    await user.click(screen.getByRole('button', { name: 'Добавить услугу' }));
    const added = item('Услуга 2');
    await user.type(added.getByLabelText(req('Название')), 'Металлорезка');
    await user.type(added.getByLabelText(req('Адрес на странице')), 'metallorezka');
    await user.click(added.getByRole('button', { name: 'Добавить пункт «Что делаем»' }));
    await user.type(added.getByLabelText('Что делаем'), 'Резка трубы в размер');

    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    await screen.findByText('Раздел «Услуги» сохранён');
    const body = bodyOf('PUT', sectionUrl('services')) as {
      items: Array<Record<string, unknown>>;
    };
    expect(body.items).toHaveLength(2);
    expect(body.items[1]).toEqual({
      slug: 'metallorezka',
      title: { ru: 'Металлорезка' },
      summary: null,
      details: [{ ru: 'Резка трубы в размер' }],
      price_note: null,
      image: null,
      cta_label: null,
    });
  });

  it('адрес услуги проверяется до отправки: формат и повторы', async () => {
    const user = await openSection('services');
    await user.click(screen.getByRole('button', { name: 'Добавить услугу' }));
    const added = item('Услуга 2');
    await user.type(added.getByLabelText(req('Название')), 'Дубль');
    await user.type(added.getByLabelText(req('Адрес на странице')), 'obzhimka-kanatov');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findByText('Такой адрес уже у услуги 1')).toBeInTheDocument();

    const slug = added.getByLabelText(req('Адрес на странице'));
    await user.clear(slug);
    await user.type(slug, 'Обжимка');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findByText('Строчная латиница, цифры и дефис')).toBeInTheDocument();
    expect(net.calls('PUT', sectionUrl('services'))).toHaveLength(0);
  });
});
