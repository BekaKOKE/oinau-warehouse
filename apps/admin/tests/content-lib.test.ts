/**
 * CMS без интерфейса: проверки полей (повторяют backend), сборка тела PUT
 * строго по схеме, сравнение форм, разбор ошибок сохранения.
 */

import { describe, expect, it } from 'vitest';

import { ApiError } from '@/lib/api/client';
import type { ContentSectionKey } from '@/lib/api/types';
import { contactsSpec } from '@/lib/content/contacts';
import { deliverySpec } from '@/lib/content/delivery';
import { pathWithin, saveFieldErrors } from '@/lib/content/errors';
import { faqSpec, MAX_FAQ_ITEMS } from '@/lib/content/faq';
import {
  bikError,
  binError,
  coordinateError,
  emailError,
  hasExtraLocale,
  httpsUrlError,
  ibanError,
  kbeError,
  linkError,
  locOut,
  phoneError,
  sameForm,
  textError,
  validateLoc,
} from '@/lib/content/fields';
import { homeSpec, splitHeroTitle } from '@/lib/content/home';
import { requisitesSpec } from '@/lib/content/requisites';
import {
  CONTENT_SECTIONS,
  isSectionKey,
  sectionSiteUrl,
  type SectionSpec,
} from '@/lib/content/sections';
import { settingsSpec } from '@/lib/content/settings';
import type { FieldErrors } from '@/lib/errors';
import { stripBasePath } from '@/lib/hooks/useLeaveGuard';

import {
  CONTACTS,
  DELIVERY,
  FAQ,
  HERO_IMAGE,
  HOME,
  OG_IMAGE,
  REQUISITES,
  SETTINGS,
  VALID_IBAN,
} from './content-fixtures';

describe('разделы', () => {
  it('ровно семь разделов backend в его порядке, со страницей витрины', () => {
    expect(CONTENT_SECTIONS.map((section) => section.key)).toEqual([
      'home',
      'contacts',
      'delivery',
      'faq',
      'requisites',
      'settings',
      'services',
    ]);
    expect(isSectionKey('faq')).toBe(true);
    expect(isSectionKey('services')).toBe(true);
    expect(sectionSiteUrl('https://oinau.kz', 'services')).toBe('https://oinau.kz/services');
    expect(isSectionKey('pages')).toBe(false);
    expect(isSectionKey('__proto__')).toBe(false);
    expect(sectionSiteUrl('https://oinau.kz/', 'requisites')).toBe(
      'https://oinau.kz/contacts#requisites',
    );
    expect(sectionSiteUrl('https://oinau.kz', 'home')).toBe('https://oinau.kz/');
  });

  it('stripBasePath: ссылки next/link приходят с /admin', () => {
    expect(stripBasePath('/admin/products')).toBe('/products');
    expect(stripBasePath('/admin')).toBe('/');
    expect(stripBasePath('/content/faq')).toBe('/content/faq');
    expect(stripBasePath('/administration')).toBe('/administration');
  });
});

describe('текст', () => {
  it('HTML, перевод строки в однострочном поле и длина по символам', () => {
    expect(textError('Цена <b>ниже</b>', 'text')).toMatch(/HTML-разметка/);
    expect(textError('<!-- x -->', 'line')).toMatch(/HTML-разметка/);
    // Знак «меньше» перед пробелом или цифрой — обычный текст.
    expect(textError('диаметр < 16 мм и <5 кг', 'line')).toBeNull();
    expect(textError('первая\nвторая', 'line')).toMatch(/Перевод строки/);
    expect(textError('первая\nвторая', 'short')).toBeNull();
    expect(textError('я'.repeat(255), 'line')).toBeNull();
    expect(textError('я'.repeat(256), 'line')).toMatch(/255/);
    // Эмодзи — один символ, как в Python, а не две UTF-16-половинки.
    expect(textError('😀'.repeat(255), 'line')).toBeNull();
  });

  it('RU обязателен: у обязательного поля и у заполненного перевода', () => {
    const errors: FieldErrors = {};
    validateLoc(errors, 'a', {}, 'line', { required: true });
    validateLoc(errors, 'b', { ru: '  ' }, 'line');
    validateLoc(errors, 'c', { ru: '', kk: 'Сұрақ' }, 'line');
    validateLoc(errors, 'd', { ru: 'ok', kk: '<i>' }, 'line');
    expect(errors).toEqual({
      a: 'Заполните текст на русском',
      c: 'Заполните русскую версию: без неё перевод не сохранится',
      'd.kk': 'HTML-разметка не допускается: поле хранит простой текст',
    });
  });

  it('locOut: пустое необязательное поле — null, пустые переводы отброшены', () => {
    expect(locOut({})).toBeNull();
    expect(locOut({ ru: '  ', kk: '' })).toBeNull();
    expect(locOut({ ru: ' Текст\r\n', kk: '' })).toEqual({ ru: 'Текст' });
    expect(locOut({ ru: 'А', kk: 'Ә' })).toEqual({ ru: 'А', kk: 'Ә' });
  });
});

describe('ссылки, телефоны, email, координаты', () => {
  it('ссылка кнопки: путь или http(s)', () => {
    expect(linkError('/catalog')).toBeNull();
    expect(linkError('https://oinau.kz/catalog?x=1')).toBeNull();
    expect(linkError('http://oinau.kz')).toBeNull();
    expect(linkError('javascript:alert(1)')).toMatch(/Допустимы только/);
    expect(linkError('data:text/html,x')).toMatch(/Допустимы только/);
    expect(linkError('//evil.test')).toMatch(/Протокол-относительные/);
    expect(linkError('/catalog page')).toMatch(/пробелы/);
    expect(linkError('https://user:pass@oinau.kz')).toMatch(/Некорректный/);
    expect(linkError('catalog')).toMatch(/Допустимы только/);
  });

  it('соцсети — только https', () => {
    expect(httpsUrlError('https://t.me/oinau')).toBeNull();
    expect(httpsUrlError('http://t.me/oinau')).toBe('Допустимы только ссылки https://');
    expect(httpsUrlError('/instagram')).toBe('Допустимы только ссылки https://');
    expect(httpsUrlError('')).toBe('Укажите ссылку');
  });

  it('телефон по правилу заявок, email, координаты', () => {
    expect(phoneError('+7 (727) 355-00-00')).toBeNull();
    expect(phoneError('+7 727 abc')).toMatch(/только цифры/);
    expect(phoneError('1234')).toMatch(/от 5 до 15 цифр/);
    expect(phoneError('1'.repeat(16))).toMatch(/от 5 до 15 цифр/);
    expect(emailError('sales@oinau.kz')).toBeNull();
    expect(emailError('sales@oinau')).toBe('Некорректный email');
    expect(coordinateError('43,238949', 90)).toBeNull();
    expect(coordinateError('91', 90)).toBe('От −90 до 90');
    expect(coordinateError('-181', 180)).toBe('От −180 до 180');
    expect(coordinateError('abc', 90)).toMatch(/Число/);
  });

  it('реквизиты РК: БИН, IBAN с контрольной суммой, БИК, КБе', () => {
    expect(binError('1234 5678 9012')).toBeNull();
    expect(binError('12345678901')).toBe('БИН/ИИН — 12 цифр');
    expect(ibanError(VALID_IBAN)).toBeNull();
    expect(ibanError('kz86 125k zt50 0410 0100')).toBeNull();
    expect(ibanError('KZ87125KZT5004100100')).toBe('Неверная контрольная сумма IBAN');
    expect(ibanError('RU86125KZT5004100100')).toMatch(/KZ \+ 18/);
    expect(bikError('hsbkkzkx')).toBeNull();
    expect(bikError('HSBKKZKX001')).toBeNull();
    expect(bikError('HSBK')).toMatch(/8 или 11/);
    expect(kbeError('17')).toBeNull();
    expect(kbeError('1')).toBe('КБе — 2 цифры');
  });
});

describe('сравнение форм', () => {
  it('uid строк, порядок ключей и пустой перевод не делают форму изменённой', () => {
    expect(
      sameForm(
        { items: [{ uid: 'row-1', question: { ru: 'А' } }] },
        { items: [{ question: { kk: '', ru: 'А' }, uid: 'row-9' }] },
      ),
    ).toBe(true);
    expect(sameForm({ a: { ru: 'А' } }, { a: { ru: 'Б' } })).toBe(false);
    expect(sameForm({ list: [1, 2] }, { list: [2, 1] })).toBe(false);
  });

  it('hasExtraLocale находит заполненный казахский текст на любой глубине', () => {
    expect(hasExtraLocale({ items: [{ q: { ru: 'А', kk: ' ' } }] })).toBe(false);
    expect(hasExtraLocale({ items: [{ q: { ru: 'А', kk: 'Ә' } }] })).toBe(true);
  });
});

// ------------------------------------------------------- тела PUT по схеме

function roundTrip<K extends ContentSectionKey, F>(
  spec: SectionSpec<K, F>,
  data: Parameters<SectionSpec<K, F>['fromData']>[0],
) {
  const form = spec.fromData(data);
  expect(spec.validate(form)).toEqual({});
  return spec.toPayload(form);
}

describe('разделы: данные → форма → тело PUT', () => {
  it('без правок тело совпадает с данными backend во всех шести разделах', () => {
    expect(roundTrip(homeSpec, HOME)).toEqual(HOME);
    expect(roundTrip(contactsSpec, CONTACTS)).toEqual(CONTACTS);
    expect(roundTrip(deliverySpec, DELIVERY)).toEqual(DELIVERY);
    expect(roundTrip(faqSpec, FAQ)).toEqual(FAQ);
    expect(roundTrip(requisitesSpec, REQUISITES)).toEqual(REQUISITES);
    expect(roundTrip(settingsSpec, SETTINGS)).toEqual(SETTINGS);
  });

  it('незаполненный раздел: пустые блоки — null, списки — пустые, лишних полей нет', () => {
    expect(homeSpec.toPayload(homeSpec.fromData({}))).toEqual({
      hero: null,
      advantages: [],
      about: null,
      seo: {
        title: null,
        description: null,
        og_title: null,
        og_description: null,
        og_image: null,
      },
    });
    expect(Object.keys(contactsSpec.toPayload(contactsSpec.fromData({})))).toEqual([
      'phones',
      'emails',
      'whatsapp',
      'address',
      'working_hours',
      'map',
      'seo',
    ]);
    expect(requisitesSpec.toPayload(requisitesSpec.fromData({}))).toEqual({
      company_name: null,
      bin: null,
      iban: null,
      bank_name: null,
      bik: null,
      kbe: null,
      legal_address: null,
    });
  });

  it('главная: кнопка — текст и ссылка вместе; hero без заголовка не сохраняется', () => {
    const form = homeSpec.fromData({});
    form.hero.cta_url = '/catalog';
    expect(homeSpec.validate(form)).toEqual({
      'hero.title': 'Заполните текст на русском',
      'hero.cta_label': 'Текст и ссылка кнопки задаются вместе',
    });
    form.hero.cta_url = 'javascript:alert(1)';
    form.hero.cta_label = { ru: 'Каталог' };
    form.hero.title = { ru: 'Заголовок' };
    expect(homeSpec.validate(form)).toEqual({
      'hero.cta_url': 'Допустимы только ссылки https://, http:// или путь /...',
    });
  });

  it('главная: ссылки на медиатеку и акцент заголовка', () => {
    expect(homeSpec.media(homeSpec.fromData(HOME))).toEqual([
      { path: 'hero.image', uuid: HERO_IMAGE },
      { path: 'seo.og_image', uuid: OG_IMAGE },
    ]);
    expect(splitHeroTitle('Комплектующие для современных площадок')).toEqual({
      head: 'Комплектующие для',
      accent: 'современных',
      tail: 'площадок',
    });
    expect(splitHeroTitle('Два слова')).toEqual({ head: 'Два слова', accent: '', tail: '' });
  });

  it('контакты: номер схлопывает пробелы, координаты — числа, пара обязательна', () => {
    const form = contactsSpec.fromData({});
    form.phones = [{ uid: 'p', number: '  +7  727 355 00 00 ', label: {} }];
    form.map = { latitude: '43,25', longitude: '' };
    expect(contactsSpec.validate(form)).toEqual({
      'map.longitude': 'Укажите долготу вместе с широтой',
    });
    form.map.longitude = '76.9';
    const payload = contactsSpec.toPayload(form);
    expect(payload.phones).toEqual([{ number: '+7 727 355 00 00', label: null }]);
    expect(payload.map).toEqual({ latitude: 43.25, longitude: 76.9 });
  });

  it('FAQ: вопрос и ответ обязательны, не больше 100 вопросов', () => {
    const form = faqSpec.fromData({});
    form.items = [{ uid: 'x', question: { ru: 'Вопрос' }, answer: {} }];
    expect(faqSpec.validate(form)).toEqual({ 'items.0.answer': 'Заполните текст на русском' });
    form.items = Array.from({ length: MAX_FAQ_ITEMS + 1 }, (_, index) => ({
      uid: `r${index}`,
      question: { ru: `В${index}` },
      answer: { ru: 'О' },
    }));
    expect(faqSpec.validate(form)).toEqual({ items: 'Не больше 100 вопросов' });
  });

  it('реквизиты уходят без пробелов и в верхнем регистре', () => {
    const form = requisitesSpec.fromData({});
    form.iban = 'kz86 125k zt50 0410 0100';
    form.bik = ' hsbkkzkx ';
    expect(requisitesSpec.validate(form)).toEqual({});
    expect(requisitesSpec.toPayload(form)).toMatchObject({ iban: VALID_IBAN, bik: 'HSBKKZKX' });
  });

  it('настройки: соцсеть выбрана и не повторяется, ссылка https', () => {
    const form = settingsSpec.fromData(SETTINGS);
    form.social_links.push(
      { uid: 'a', network: 'INSTAGRAM', url: 'http://instagram.com/x' },
      { uid: 'b', network: '', url: 'https://t.me/x' },
    );
    expect(settingsSpec.validate(form)).toEqual({
      'social_links.1.network': 'Каждая соцсеть указывается один раз',
      'social_links.1.url': 'Допустимы только ссылки https://',
      'social_links.2.network': 'Выберите соцсеть',
    });
  });
});

describe('ошибки сохранения', () => {
  it('422 — по путям полей; 404/409 медиатеки — у поля с этим UUID', () => {
    const invalid = new ApiError(422, 'validation_error', 'Ошибка', {
      fields: [{ loc: ['body', 'items', 0, 'answer'], msg: 'Value error, Текст длиннее 5000' }],
    });
    expect(saveFieldErrors(invalid, [])).toEqual({ 'items.0.answer': 'Текст длиннее 5000' });

    const refs = [
      { path: 'hero.image', uuid: HERO_IMAGE },
      { path: 'seo.og_image', uuid: OG_IMAGE },
    ];
    const missing = new ApiError(404, 'media_not_found', 'Файл медиатеки не найден', {
      media_uuids: [OG_IMAGE],
    });
    expect(saveFieldErrors(missing, refs)).toEqual({
      'seo.og_image': 'Файл не найден в медиатеке — выберите другое изображение',
    });
    const failed = new ApiError(409, 'media_failed', 'Файл отвергнут', {
      media_uuids: [HERO_IMAGE],
    });
    expect(saveFieldErrors(failed, refs)).toEqual({
      'hero.image': 'Файл отклонён при обработке — загрузите другое изображение',
    });
    expect(saveFieldErrors(new ApiError(403, 'forbidden', 'Нет'), refs)).toEqual({});
  });

  it('pathWithin: префикс только по границе сегмента', () => {
    expect(pathWithin('items.0.answer', ['items'])).toBe(true);
    expect(pathWithin('items', ['items'])).toBe(true);
    expect(pathWithin('itemsCount', ['items'])).toBe(false);
  });
});
