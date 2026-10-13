/**
 * Каркас страниц входа, регистрации и восстановления доступа.
 *
 * Белая карточка с формой и узкая navy-панель с тем, зачем нужен
 * кабинет. На телефоне панель уходит вниз и сжимается до списка —
 * форма всегда первая.
 */

import Image from 'next/image';
import Link from 'next/link';
import type { ReactNode } from 'react';

import styles from './Cabinet.module.css';

const BENEFITS = [
  { title: 'История заявок', text: 'Статусы, суммы и ответы менеджера по каждой заявке.' },
  { title: 'Проекты', text: 'Собирайте позиции под конкретную площадку или объект.' },
  { title: 'Избранное в аккаунте', text: 'Список доступен с любого устройства.' },
];

export function AuthLayout({
  title,
  lead,
  children,
  footer,
  wide = false,
}: {
  title: string;
  lead?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  return (
    <div className={styles.auth}>
      <div className={`${styles.authGrid} ${wide ? styles.authGridWide : ''}`}>
        <section className={styles.authCard}>
          <Link href="/" className={styles.authBack}>
            ← На сайт
          </Link>
          <p className={styles.eyebrow}>Личный кабинет</p>
          <h1 className={styles.authTitle}>{title}</h1>
          {lead ? <p className={styles.authLead}>{lead}</p> : null}
          <div className={styles.authBody}>{children}</div>
          {footer ? <div className={styles.authFooter}>{footer}</div> : null}
        </section>

        <aside className={styles.authAside} aria-label="Возможности кабинета">
          <Image
            src="/brand/logo-white.png"
            alt="OINAU PRO"
            width={1000}
            height={255}
            className={styles.authAsideLogo}
          />
          <p className={styles.authAsideTitle}>Личный кабинет клиента</p>
          <ul className={styles.authBenefits}>
            {BENEFITS.map((item) => (
              <li key={item.title}>
                <span className={styles.authBenefitMark} aria-hidden="true" />
                <div>
                  <p className={styles.authBenefitTitle}>{item.title}</p>
                  <p className={styles.authBenefitText}>{item.text}</p>
                </div>
              </li>
            ))}
          </ul>
          <p className={styles.authAsideNote}>
            Заявку по-прежнему можно отправить без регистрации — кабинет лишь хранит историю.
          </p>
        </aside>
      </div>
    </div>
  );
}
