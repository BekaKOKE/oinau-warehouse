/**
 * Шапка: навигация, поиск, счётчики и вход в кабинет.
 */

import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { Providers } from '@/components/layout/Providers';
import { SiteHeader } from '@/components/layout/SiteHeader';
import { isNavActive } from '@/lib/navigation';
import { makeCategories } from './factories';
import { navigationState, routerPush } from './setup';

function renderHeader() {
  return render(
    <Providers>
      <SiteHeader categories={makeCategories()} />
    </Providers>,
  );
}

describe('SiteHeader', () => {
  it('содержит логотип и основные разделы', () => {
    renderHeader();
    expect(screen.getByRole('link', { name: 'OINAU PRO — на главную' })).toHaveAttribute(
      'href',
      '/',
    );
    const nav = screen.getByRole('navigation', { name: 'Основная навигация' });
    expect(nav).toBeInTheDocument();
    for (const label of ['Каталог', 'Услуги', 'Доставка', 'Вопросы', 'Контакты']) {
      expect(screen.getAllByRole('link', { name: label }).length).toBeGreaterThan(0);
    }
  });

  it('на главной «Каталог» не выглядит активным', () => {
    navigationState.pathname = '/';
    renderHeader();
    const nav = screen.getByRole('navigation', { name: 'Основная навигация' });
    for (const link of within(nav).getAllByRole('link')) {
      expect(link).not.toHaveAttribute('aria-current');
    }
  });

  it.each(['/catalog', '/catalog/kanaty-i-seti'])('на %s активен только «Каталог»', (path) => {
    navigationState.pathname = path;
    renderHeader();
    const nav = screen.getByRole('navigation', { name: 'Основная навигация' });
    expect(within(nav).getByRole('link', { name: 'Каталог' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(within(nav).getByRole('link', { name: 'Контакты' })).not.toHaveAttribute('aria-current');
  });

  it('активный пункт определяется границей сегмента маршрута', () => {
    expect(isNavActive('/', '/catalog')).toBe(false);
    expect(isNavActive('/catalog', '/catalog')).toBe(true);
    expect(isNavActive('/catalog/gorki-i-elementy', '/catalog')).toBe(true);
    expect(isNavActive('/catalogue', '/catalog')).toBe(false);
    expect(isNavActive('/product/zatsep', '/catalog')).toBe(false);
    expect(isNavActive(null, '/catalog')).toBe(false);
  });

  it('поле поиска подсказывает, что искать', () => {
    renderHeader();
    expect(screen.getByRole('searchbox', { name: 'Поиск по каталогу' })).toHaveAttribute(
      'placeholder',
      'Поиск по артикулу или названию',
    );
  });

  it('кнопка «Войти» ведёт на заглушку кабинета', () => {
    renderHeader();
    expect(screen.getByRole('link', { name: 'Войти' })).toHaveAttribute('href', '/cabinet/login');
  });

  it('поиск переводит в каталог с запросом в URL', async () => {
    const user = userEvent.setup();
    renderHeader();

    await user.type(screen.getByRole('searchbox', { name: 'Поиск по каталогу' }), 'канат 16');
    await user.click(screen.getByRole('button', { name: 'Найти' }));

    expect(routerPush).toHaveBeenCalledWith('/catalog?search=%D0%BA%D0%B0%D0%BD%D0%B0%D1%82+16');
  });

  it('пустой поиск открывает каталог без параметров', async () => {
    const user = userEvent.setup();
    renderHeader();

    await user.type(screen.getByRole('searchbox', { name: 'Поиск по каталогу' }), '   ');
    await user.click(screen.getByRole('button', { name: 'Найти' }));

    expect(routerPush).toHaveBeenCalledWith('/catalog');
  });

  it('кнопки шапки имеют доступное имя', () => {
    renderHeader();
    expect(screen.getByRole('link', { name: 'Избранное' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Корзина' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Быстрый заказ' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Открыть меню' })).toBeInTheDocument();
  });

  it('телефон и часы работы берутся из CMS', () => {
    render(
      <Providers>
        <SiteHeader
          categories={makeCategories()}
          contacts={{
            phones: [{ tel: '+77270000000', display: '+7 727 000 00 00', label: 'Отдел продаж' }],
            working_hours: 'Пн–Пт 9:00–18:00',
            seo: { title: null, description: null, og_image: null },
          }}
        />
      </Providers>,
    );
    expect(screen.getByRole('link', { name: '+7 727 000 00 00' })).toHaveAttribute(
      'href',
      'tel:+77270000000',
    );
    expect(screen.getByText('Пн–Пт 9:00–18:00 · Отдел продаж')).toBeInTheDocument();
  });

  it('без контактов в CMS телефон не выдумывается', () => {
    renderHeader();
    expect(screen.queryByRole('link', { name: /^\+7/ })).not.toBeInTheDocument();
  });

  it('«Быстрый заказ» открывает окно с тремя способами заказа', async () => {
    const user = userEvent.setup();
    renderHeader();

    await user.click(screen.getByRole('button', { name: 'Быстрый заказ' }));

    const dialog = screen.getByRole('dialog', { name: 'Быстрый заказ' });
    expect(
      within(dialog)
        .getAllByRole('tab')
        .map((tab) => tab.textContent),
    ).toEqual(['По телефону', 'По артикулам', 'Запрос КП']);
  });

  it('мобильное меню открывается и показывает категории', async () => {
    const user = userEvent.setup();
    renderHeader();

    await user.click(screen.getByRole('button', { name: 'Открыть меню' }));

    const menu = screen.getByRole('navigation', { name: 'Меню' });
    expect(menu).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Канаты и сети/ })).toHaveAttribute(
      'href',
      '/catalog/kanaty-i-seti',
    );

    await user.click(screen.getByRole('button', { name: 'Закрыть меню' }));
    expect(screen.queryByRole('navigation', { name: 'Меню' })).not.toBeInTheDocument();
  });

  it('кнопка корзины открывает панель', async () => {
    const user = userEvent.setup();
    renderHeader();

    await user.click(screen.getByRole('button', { name: 'Корзина' }));

    expect(screen.getByRole('dialog', { name: 'Корзина' })).toBeInTheDocument();
  });
});
