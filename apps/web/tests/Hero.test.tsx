/**
 * Главный экран: утверждённый заголовок с акцентом и действия.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { Hero, splitTitle } from '@/components/home/Hero';
import { Providers } from '@/components/layout/Providers';

describe('splitTitle', () => {
  it('подсвечивает предпоследнее слово утверждённого заголовка', () => {
    expect(splitTitle('Комплектующие для современных площадок')).toEqual({
      head: 'Комплектующие для',
      accent: 'современных',
      tail: 'площадок',
    });
  });

  it('короткий заголовок из CMS выводится без акцента', () => {
    expect(splitTitle('Каталог  ')).toEqual({ head: 'Каталог', accent: '', tail: '' });
  });
});

describe('Hero', () => {
  function renderHero(content: Parameters<typeof Hero>[0]['content'] = null) {
    return render(
      <Providers>
        <Hero content={content} />
      </Providers>,
    );
  }

  it('без CMS показывает утверждённый заголовок и кнопку каталога', () => {
    renderHero();
    const title = screen.getByRole('heading', { level: 1 });
    expect(title).toHaveTextContent('Комплектующие для современных площадок');
    expect(title.querySelector('span')).toHaveTextContent('современных');
    expect(screen.getByRole('link', { name: /Перейти в каталог/ })).toHaveAttribute(
      'href',
      '/catalog',
    );
  });

  it('заголовок из CMS имеет приоритет', () => {
    renderHero({
      hero: {
        title: 'Комплектующие для надёжных площадок',
        subtitle: 'Текст',
        cta_label: 'В каталог',
        cta_url: '/catalog',
        image: null,
      },
    } as Parameters<typeof Hero>[0]['content']);
    expect(screen.getByRole('heading', { level: 1 }).querySelector('span')).toHaveTextContent(
      'надёжных',
    );
  });

  it('«Быстрый заказ» в hero открывает окно заказа', async () => {
    const user = userEvent.setup();
    renderHero();

    await user.click(screen.getByRole('button', { name: 'Быстрый заказ' }));

    expect(screen.getByRole('dialog', { name: 'Быстрый заказ' })).toBeInTheDocument();
  });
});
