/**
 * Верхнее меню B2B-каталога: разделы слева, «Доставка» и «Контакты»
 * справа — рядом с телефоном и корзиной.
 */

import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Providers } from '@/components/layout/Providers';
import { SiteHeader } from '@/components/layout/SiteHeader';
import { NAV_LINKS, NAV_PRIMARY, NAV_SECONDARY } from '@/lib/navigation';
import { makeCategories } from './factories';
import { navigationState } from './setup';

describe('навигация', () => {
  it('«Доставка» перенесена в правую группу вместе с «Контактами»', () => {
    expect(NAV_PRIMARY.map((link) => link.label)).toEqual(['Каталог', 'Услуги', 'Вопросы']);
    expect(NAV_SECONDARY.map((link) => link.label)).toEqual(['Доставка', 'Контакты']);
    expect(NAV_LINKS).toHaveLength(5);
  });

  it('в шапке правая группа идёт после разделов', () => {
    navigationState.pathname = '/';
    render(
      <Providers>
        <SiteHeader categories={makeCategories()} />
      </Providers>,
    );
    const nav = screen.getByRole('navigation', { name: 'Основная навигация' });
    const labels = within(nav)
      .getAllByRole('link')
      .map((link) => link.textContent);
    expect(labels).toEqual(['Каталог', 'Услуги', 'Вопросы', 'Доставка', 'Контакты']);
  });

  it('«Услуги» подсвечивается на своей странице', () => {
    navigationState.pathname = '/services';
    render(
      <Providers>
        <SiteHeader categories={makeCategories()} />
      </Providers>,
    );
    const nav = screen.getByRole('navigation', { name: 'Основная навигация' });
    expect(within(nav).getByRole('link', { name: 'Услуги' })).toHaveAttribute(
      'aria-current',
      'page',
    );
  });

  it('рядом с телефоном — ссылка на WhatsApp из CMS', () => {
    render(
      <Providers>
        <SiteHeader
          categories={makeCategories()}
          contacts={{
            phones: [{ tel: '+77270000000', display: '+7 727 000 00 00', label: null }],
            whatsapp: { display: '+7 701 000 00 00', url: 'https://wa.me/77010000000' },
            seo: { title: null, description: null, og_image: null },
          }}
        />
      </Providers>,
    );
    const link = screen.getByRole('link', { name: 'Написать в WhatsApp' });
    expect(link).toHaveAttribute('href', 'https://wa.me/77010000000');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });
});
