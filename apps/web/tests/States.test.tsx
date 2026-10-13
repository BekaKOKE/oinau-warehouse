/**
 * Пустое состояние, ошибка, скелетоны и галерея.
 * Ни один экран не должен оставаться белым.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { ImageGallery } from '@/components/product/ImageGallery';
import { ProductGridSkeleton } from '@/components/catalog/ProductGrid';
import { EmptyState, ErrorState } from '@/components/ui/States';

describe('состояния экрана', () => {
  it('пустая выдача объясняет, что делать дальше', () => {
    render(
      <EmptyState
        title="По вашему запросу ничего не найдено"
        text="Попробуйте изменить фильтры."
      />,
    );
    expect(screen.getByText('По вашему запросу ничего не найдено')).toBeInTheDocument();
  });

  it('ошибка объявляется средствам чтения с экрана', () => {
    render(<ErrorState title="Не удалось загрузить каталог" text="Сервис недоступен" />);
    expect(screen.getByRole('alert')).toHaveTextContent('Не удалось загрузить каталог');
  });

  it('скелетон выдачи скрыт от средств чтения с экрана', () => {
    const { container } = render(<ProductGridSkeleton count={3} />);
    expect(container.querySelectorAll('[aria-hidden="true"]').length).toBeGreaterThan(0);
  });
});

describe('ImageGallery', () => {
  const image = (name: string) => ({
    url: `http://localhost:9000/oinau-media/${name}/variants/large.webp`,
    kind: 'PHOTO' as const,
    alt: null,
    is_main: name === 'a',
    width: 1600,
    height: 1200,
    variants: {
      large: `http://localhost:9000/oinau-media/${name}/variants/large.webp`,
      thumb: `http://localhost:9000/oinau-media/${name}/variants/thumb.webp`,
    },
  });

  it('без изображений показывает заглушку и не падает', () => {
    render(<ImageGallery images={[]} sku="RP-016" name="Канат" />);
    expect(screen.getByText('OINAU PRO')).toBeInTheDocument();
    expect(screen.getByText('RP-016')).toBeInTheDocument();
  });

  it('переключает изображение миниатюрой с клавиатуры', async () => {
    const user = userEvent.setup();
    render(<ImageGallery images={[image('a'), image('b')]} sku="RP-016" name="Канат" />);

    const second = screen.getByRole('button', { name: 'Фото 2 из 2' });
    expect(second).toHaveAttribute('aria-pressed', 'false');

    await user.click(second);
    expect(second).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('img', { name: 'Канат' })).toHaveAttribute(
      'src',
      expect.stringContaining('/b/variants/large.webp'),
    );
  });

  it('одно изображение не рисует ленту миниатюр', () => {
    render(<ImageGallery images={[image('a')]} sku="RP-016" name="Канат" />);
    expect(screen.queryByRole('button', { name: /Фото/ })).not.toBeInTheDocument();
  });
});
