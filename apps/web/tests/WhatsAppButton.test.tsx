/**
 * Плавающая кнопка WhatsApp не должна закрывать нажимаемые элементы:
 * над кнопкой «В заявку», полем формы или ссылкой она прячется.
 */

import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { WhatsAppButton } from '@/components/layout/WhatsAppButton';

const RECT = {
  left: 330,
  top: 780,
  right: 378,
  bottom: 828,
  width: 48,
  height: 48,
  x: 330,
  y: 780,
};

let underButton: Element[] = [];

beforeEach(() => {
  underButton = [];
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
    callback(0);
    return 1;
  });
  Object.defineProperty(document, 'elementsFromPoint', {
    configurable: true,
    value: () => underButton,
  });
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
    ...RECT,
    toJSON: () => RECT,
  } as DOMRect);
});

afterEach(() => {
  // @ts-expect-error — возвращаем jsdom в исходное состояние
  delete document.elementsFromPoint;
});

function scroll() {
  act(() => {
    window.dispatchEvent(new Event('scroll'));
  });
}

describe('WhatsAppButton', () => {
  it('видна, когда под ней нет нажимаемых элементов', () => {
    render(<WhatsAppButton url="https://wa.me/77270000000" />);
    const link = screen.getByRole('link', { name: 'Написать в WhatsApp' });
    expect(link).toHaveAttribute('href', 'https://wa.me/77270000000');
    expect(link).not.toHaveAttribute('data-hidden');
  });

  it('прячется над кнопкой «В заявку» и возвращается, когда место свободно', () => {
    const cta = document.createElement('button');
    cta.textContent = 'В заявку';
    document.body.append(cta);

    render(<WhatsAppButton url="https://wa.me/77270000000" />);
    const link = screen.getByRole('link', { name: 'Написать в WhatsApp' });

    underButton = [cta, document.body];
    scroll();
    expect(link).toHaveAttribute('data-hidden', 'true');

    underButton = [document.body];
    scroll();
    expect(link).not.toHaveAttribute('data-hidden');
    cta.remove();
  });

  it('прячется, пока в поле формы стоит курсор', () => {
    const input = document.createElement('input');
    document.body.append(input);
    render(<WhatsAppButton url="https://wa.me/77270000000" />);

    act(() => input.focus());
    expect(screen.getByRole('link', { name: 'Написать в WhatsApp' })).toHaveAttribute(
      'data-hidden',
      'true',
    );
    input.remove();
  });
});
