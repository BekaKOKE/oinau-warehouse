/**
 * Элементы управления каталогом: фильтры, сортировка, снятие плашек
 * и постраничная навигация. Все они обязаны менять URL, а не только
 * состояние компонента.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { CatalogFilters } from '@/components/catalog/CatalogFilters';
import { CatalogToolbar } from '@/components/catalog/CatalogToolbar';
import { CategoryTabs } from '@/components/catalog/CategoryTabs';
import { Pagination, pageWindow } from '@/components/catalog/Pagination';
import { parseCatalogParams } from '@/lib/catalog-params';
import { makeCategories } from './factories';
import { routerPush } from './setup';

describe('CatalogFilters', () => {
  it('выбор наличия переписывает URL и сбрасывает страницу', async () => {
    const user = userEvent.setup();
    render(<CatalogFilters filters={parseCatalogParams({ page: '3' })} />);

    await user.click(screen.getByRole('radio', { name: 'В наличии' }));

    expect(routerPush).toHaveBeenCalledWith('/catalog?availability=IN_STOCK');
  });

  it('диапазон цены применяется отправкой формы', async () => {
    const user = userEvent.setup();
    render(<CatalogFilters filters={parseCatalogParams({})} />);

    await user.type(screen.getByRole('spinbutton', { name: /Цена от/ }), '1000');
    await user.type(screen.getByRole('spinbutton', { name: /Цена до/ }), '5000');
    await user.click(screen.getByRole('button', { name: 'Применить' }));

    expect(routerPush).toHaveBeenCalledWith('/catalog?min_price=1000&max_price=5000');
  });

  it('показывает «Сбросить» только при активных фильтрах', () => {
    const { unmount } = render(<CatalogFilters filters={parseCatalogParams({})} />);
    expect(screen.queryByRole('link', { name: 'Сбросить' })).not.toBeInTheDocument();
    unmount();

    render(<CatalogFilters filters={parseCatalogParams({ availability: 'IN_STOCK' })} />);
    expect(screen.getByRole('link', { name: 'Сбросить' })).toHaveAttribute('href', '/catalog');
  });

  it('на странице категории сброс не уводит из раздела', () => {
    render(
      <CatalogFilters
        filters={parseCatalogParams({ availability: 'IN_STOCK' }, { category: 'kanaty-i-seti' })}
        basePath="/catalog/kanaty-i-seti"
        lockCategory
      />,
    );
    expect(screen.getByRole('link', { name: 'Сбросить' })).toHaveAttribute(
      'href',
      '/catalog/kanaty-i-seti',
    );
  });
});

describe('CatalogToolbar', () => {
  it('показывает число найденных позиций', () => {
    render(<CatalogToolbar filters={parseCatalogParams({})} total={20} />);
    expect(screen.getByText('Найдено 20 товаров')).toBeInTheDocument();
  });

  it('сортировка переписывает URL', async () => {
    const user = userEvent.setup();
    render(<CatalogToolbar filters={parseCatalogParams({})} total={20} />);

    await user.selectOptions(screen.getByRole('combobox', { name: 'Сортировка' }), 'price_asc');

    expect(routerPush).toHaveBeenCalledWith('/catalog?sort=price_asc');
  });

  it('плашка активного фильтра снимает его ссылкой', () => {
    render(
      <CatalogToolbar
        filters={parseCatalogParams({ availability: 'IN_STOCK', search: 'канат' })}
        total={4}
      />,
    );

    const chip = screen.getByRole('link', { name: 'Снять фильтр: В наличии' });
    expect(chip).toHaveAttribute('href', '/catalog?search=%D0%BA%D0%B0%D0%BD%D0%B0%D1%82');
  });
});

describe('CategoryTabs', () => {
  it('показывает разделы со счётчиками и отмечает активный', () => {
    render(
      <CategoryTabs categories={makeCategories()} activeSlug="kanaty-i-seti" totalProducts={20} />,
    );

    const active = screen.getByRole('link', { name: /Канаты и сети/ });
    expect(active).toHaveAttribute('href', '/catalog/kanaty-i-seti');
    expect(active).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: /Все категории/ })).not.toHaveAttribute('aria-current');
  });
});

describe('Pagination', () => {
  const filters = parseCatalogParams({ page: '2', sort: 'price_asc' });

  it('не выводится, когда страница одна', () => {
    const { container } = render(
      <Pagination filters={filters} page={1} pages={1} total={5} shown={5} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('ссылки сохраняют остальные фильтры', () => {
    render(<Pagination filters={filters} page={2} pages={5} total={120} shown={24} />);

    expect(screen.getByRole('link', { name: 'Страница 3' })).toHaveAttribute(
      'href',
      '/catalog?sort=price_asc&page=3',
    );
    expect(screen.getByRole('link', { name: 'Предыдущая страница' })).toHaveAttribute(
      'href',
      '/catalog?sort=price_asc',
    );
  });

  it('отмечает текущую страницу и блокирует край', () => {
    render(<Pagination filters={filters} page={1} pages={5} total={120} shown={24} />);

    expect(screen.getByRole('link', { name: 'Страница 1' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(screen.getByRole('link', { name: 'Предыдущая страница' })).toHaveAttribute(
      'aria-disabled',
      'true',
    );
    expect(screen.getByText('Показано 24 из 120')).toBeInTheDocument();
  });

  it('окно страниц сворачивает середину', () => {
    expect(pageWindow(1, 5)).toEqual([1, 2, 3, 4, 5]);
    expect(pageWindow(10, 32)).toEqual([1, 'gap', 9, 10, 11, 'gap', 32]);
    expect(pageWindow(2, 32)).toEqual([1, 2, 3, 4, 'gap', 32]);
    expect(pageWindow(32, 32)).toEqual([1, 'gap', 29, 30, 31, 32]);
  });
});
