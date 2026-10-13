/**
 * Вход, регистрация, подтверждение email и восстановление пароля.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { StrictMode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@oinau/api-client';

import { LoginForm } from '@/components/cabinet/LoginForm';
import { RegisterForm } from '@/components/cabinet/RegisterForm';
import { ResetPasswordView } from '@/components/cabinet/ResetPasswordView';
import { VerifyEmailView } from '@/components/cabinet/VerifyEmailView';
import { Providers } from '@/components/layout/Providers';
import { authApi, customerApi, regionsApi, resetCabinetMocks, sessionState } from './cabinet-mocks';
import { routerReplace } from './setup';

vi.mock('@/lib/api/customer', async () => ({ ...(await import('./cabinet-mocks')).customerApi }));
vi.mock('@/lib/api/customer-auth', async () => ({ ...(await import('./cabinet-mocks')).authApi }));
vi.mock('@/lib/api/requests', async () => ({
  ...(await import('./cabinet-mocks')).regionsApi,
  newIdempotencyKey: () => 'test-key',
}));
vi.mock('@/lib/cabinet/session', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/cabinet/session')>();
  const { sessionState: state } = await import('./cabinet-mocks');
  return {
    ...actual,
    hasSessionHint: () => state.hint,
    getAccessToken: async () => state.token,
  };
});

const PASSWORD = 'customer-strong-password';

function renderUi(ui: React.ReactNode) {
  return render(<Providers>{ui}</Providers>);
}

beforeEach(() => {
  resetCabinetMocks();
});

describe('вход', () => {
  it('входит и возвращает на страницу из next', async () => {
    const user = userEvent.setup();
    authApi.loginCustomer.mockImplementation(async () => {
      sessionState.hint = true;
      sessionState.token = 'access-token';
      return { access_token: 'access-token', token_type: 'bearer', expires_in: 900 };
    });
    renderUi(<LoginForm next="/cabinet/requests" />);

    await user.type(screen.getByLabelText(/Email/), '  buyer@park-group.kz ');
    await user.type(screen.getByLabelText(/Пароль/, { selector: 'input' }), PASSWORD);
    await user.click(screen.getByRole('button', { name: 'Войти' }));

    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith('/cabinet/requests'));
    expect(authApi.loginCustomer).toHaveBeenCalledWith({
      email: 'buyer@park-group.kz',
      password: PASSWORD,
    });
    expect(customerApi.fetchProfile).toHaveBeenCalled();
  });

  it('внешний адрес в next игнорируется', async () => {
    const user = userEvent.setup();
    authApi.loginCustomer.mockResolvedValue({ access_token: 't', expires_in: 900 });
    renderUi(<LoginForm next="https://evil.example/phish" />);

    await user.type(screen.getByLabelText(/Email/), 'buyer@park-group.kz');
    await user.type(screen.getByLabelText(/Пароль/, { selector: 'input' }), PASSWORD);
    await user.click(screen.getByRole('button', { name: 'Войти' }));

    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith('/cabinet'));
  });

  it('показывает ошибку неверного пароля, а не «сессия истекла»', async () => {
    const user = userEvent.setup();
    authApi.loginCustomer.mockRejectedValue(
      new ApiError(401, 'invalid_credentials', 'Неверный email или пароль'),
    );
    renderUi(<LoginForm />);

    await user.type(screen.getByLabelText(/Email/), 'buyer@park-group.kz');
    await user.type(screen.getByLabelText(/Пароль/, { selector: 'input' }), 'wrong-password-123');
    await user.click(screen.getByRole('button', { name: 'Войти' }));

    expect(await screen.findByText('Неверный email или пароль')).toBeInTheDocument();
    expect(routerReplace).not.toHaveBeenCalled();
  });

  it('неподтверждённый email предлагает отправить письмо повторно', async () => {
    const user = userEvent.setup();
    authApi.loginCustomer.mockRejectedValue(
      new ApiError(403, 'email_not_verified', 'Подтвердите email'),
    );
    authApi.resendVerification.mockResolvedValue({ detail: 'Письмо отправлено повторно.' });
    renderUi(<LoginForm />);

    await user.type(screen.getByLabelText(/Email/), 'buyer@park-group.kz');
    await user.type(screen.getByLabelText(/Пароль/, { selector: 'input' }), PASSWORD);
    await user.click(screen.getByRole('button', { name: 'Войти' }));
    await user.click(await screen.findByRole('button', { name: 'Отправить письмо ещё раз' }));

    expect(authApi.resendVerification).toHaveBeenCalledWith('buyer@park-group.kz');
    expect(await screen.findByText('Письмо отправлено повторно.')).toBeInTheDocument();
  });

  it('проверяет поля до отправки и умеет показать пароль', async () => {
    const user = userEvent.setup();
    renderUi(<LoginForm />);

    await user.click(screen.getByRole('button', { name: 'Войти' }));
    expect(screen.getByText('Введите email')).toBeInTheDocument();
    expect(screen.getByText('Введите пароль')).toBeInTheDocument();
    expect(authApi.loginCustomer).not.toHaveBeenCalled();

    const input = screen.getByLabelText(/Пароль/, { selector: 'input' });
    expect(input).toHaveAttribute('type', 'password');
    await user.click(screen.getByRole('button', { name: 'Показать пароль' }));
    expect(input).toHaveAttribute('type', 'text');
  });

  it('ссылки на восстановление пароля', () => {
    renderUi(<LoginForm />);
    expect(screen.getByRole('link', { name: 'Забыли пароль?' })).toHaveAttribute(
      'href',
      '/cabinet/reset-password',
    );
  });
});

describe('регистрация', () => {
  async function fillRegistration(user: ReturnType<typeof userEvent.setup>) {
    await user.type(screen.getByLabelText(/Email/), 'buyer@park-group.kz');
    await user.type(screen.getByLabelText(/Пароль/, { selector: 'input' }), PASSWORD);
    await user.type(screen.getByLabelText(/Контактное лицо/), 'Айгерим');
    await user.type(screen.getByLabelText(/Телефон/), '+7 701 000 00 00');
  }

  it('без обязательных полей не отправляет запрос', async () => {
    const user = userEvent.setup();
    renderUi(<RegisterForm />);

    await user.click(screen.getByRole('button', { name: 'Зарегистрироваться' }));

    expect(screen.getByText('Укажите контактное лицо')).toBeInTheDocument();
    expect(authApi.registerCustomer).not.toHaveBeenCalled();
  });

  it('после отправки — экран «Проверьте email» без признака существования адреса', async () => {
    const user = userEvent.setup();
    authApi.registerCustomer.mockResolvedValue({ detail: 'Проверьте почту.' });
    renderUi(<RegisterForm />);

    await fillRegistration(user);
    await user.click(screen.getByRole('button', { name: 'Зарегистрироваться' }));

    expect(await screen.findByRole('heading', { name: 'Проверьте email' })).toBeInTheDocument();
    expect(screen.getByText(/Если адрес/)).toBeInTheDocument();
    expect(authApi.registerCustomer).toHaveBeenCalledWith({
      email: 'buyer@park-group.kz',
      password: PASSWORD,
      contact_name: 'Айгерим',
      company_name: null,
      phone: '+7 701 000 00 00',
    });
  });

  it('регион не запрашивается: поля «Регион» на форме нет', () => {
    renderUi(<RegisterForm />);

    expect(screen.queryByLabelText(/Регион/)).not.toBeInTheDocument();
    expect(regionsApi.fetchRegions).not.toHaveBeenCalled();
  });

  it('ошибки полей от backend показываются у полей', async () => {
    const user = userEvent.setup();
    authApi.registerCustomer.mockRejectedValue(
      new ApiError(422, 'validation_error', 'Ошибка', {
        fields: [{ loc: ['body', 'phone'], msg: 'Value error, Номер не существует' }],
      }),
    );
    renderUi(<RegisterForm />);

    await fillRegistration(user);
    await user.click(screen.getByRole('button', { name: 'Зарегистрироваться' }));

    expect(await screen.findByText('Номер не существует')).toBeInTheDocument();
    expect(screen.getByLabelText(/Телефон/)).toHaveAttribute('aria-invalid', 'true');
  });
});

describe('подтверждение email', () => {
  it('отправляет одноразовый токен ровно один раз даже в StrictMode', async () => {
    authApi.verifyEmail.mockResolvedValue(undefined);
    render(
      <StrictMode>
        <Providers>
          <VerifyEmailView token="verification-token-1234567890" />
        </Providers>
      </StrictMode>,
    );

    expect(await screen.findByRole('heading', { name: 'Email подтверждён' })).toBeInTheDocument();
    expect(authApi.verifyEmail).toHaveBeenCalledTimes(1);
    expect(authApi.verifyEmail).toHaveBeenCalledWith('verification-token-1234567890');
  });

  it('устаревшая ссылка — ошибка и форма повторной отправки', async () => {
    const user = userEvent.setup();
    authApi.verifyEmail.mockRejectedValue(
      new ApiError(422, 'invalid_token', 'Ссылка недействительна или устарела. Запросите новую'),
    );
    authApi.resendVerification.mockResolvedValue({ detail: 'Письмо отправлено повторно.' });
    renderUi(<VerifyEmailView token="expired-token-1234567890" />);

    expect(await screen.findByText(/Ссылка недействительна/)).toBeInTheDocument();
    await user.type(screen.getByLabelText(/Email/), 'buyer@park-group.kz');
    await user.click(screen.getByRole('button', { name: 'Отправить письмо' }));

    expect(await screen.findByText('Письмо отправлено повторно.')).toBeInTheDocument();
  });

  it('без токена не обращается к API', () => {
    renderUi(<VerifyEmailView />);
    expect(screen.getByRole('heading', { name: 'Ссылка неполная' })).toBeInTheDocument();
    expect(authApi.verifyEmail).not.toHaveBeenCalled();
  });
});

describe('восстановление пароля', () => {
  it('запрос ссылки заканчивается одинаковым сообщением', async () => {
    const user = userEvent.setup();
    authApi.requestPasswordReset.mockResolvedValue({ detail: 'ok' });
    renderUi(<ResetPasswordView />);

    await user.type(screen.getByLabelText(/Email/), 'nobody@example.kz');
    await user.click(screen.getByRole('button', { name: 'Получить ссылку' }));

    expect(await screen.findByText(/Если аккаунт с таким адресом существует/)).toBeInTheDocument();
    expect(authApi.requestPasswordReset).toHaveBeenCalledWith('nobody@example.kz');
  });

  it('новый пароль: несовпадение не отправляется, успех ведёт ко входу', async () => {
    const user = userEvent.setup();
    authApi.confirmPasswordReset.mockResolvedValue(undefined);
    renderUi(<ResetPasswordView token="reset-token-1234567890" />);

    const [first, second] = screen.getAllByLabelText(/пароль/i, { selector: 'input' });
    await user.type(first!, PASSWORD);
    await user.type(second!, 'другой-пароль-123');
    await user.click(screen.getByRole('button', { name: 'Сохранить пароль' }));
    expect(screen.getByText('Пароли не совпадают')).toBeInTheDocument();
    expect(authApi.confirmPasswordReset).not.toHaveBeenCalled();

    await user.clear(second!);
    await user.type(second!, PASSWORD);
    await user.click(screen.getByRole('button', { name: 'Сохранить пароль' }));

    expect(await screen.findByRole('heading', { name: 'Пароль изменён' })).toBeInTheDocument();
    expect(authApi.confirmPasswordReset).toHaveBeenCalledWith('reset-token-1234567890', PASSWORD);
    expect(screen.getByRole('link', { name: 'Войти' })).toHaveAttribute('href', '/cabinet/login');
  });

  it('недействительная ссылка предлагает запросить новую', async () => {
    const user = userEvent.setup();
    authApi.confirmPasswordReset.mockRejectedValue(
      new ApiError(422, 'invalid_token', 'Ссылка недействительна или устарела. Запросите новую'),
    );
    renderUi(<ResetPasswordView token="used-token-1234567890" />);

    for (const input of screen.getAllByLabelText(/пароль/i, { selector: 'input' })) {
      await user.type(input, PASSWORD);
    }
    await user.click(screen.getByRole('button', { name: 'Сохранить пароль' }));

    expect(await screen.findByText(/Ссылка недействительна/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Запросить новую ссылку' })).toBeInTheDocument();
  });
});
