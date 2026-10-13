/**
 * Главный экран — компактная синяя полоса: слева заголовок
 * и подзаголовок, справа два действия (быстрый заказ и каталог).
 * На узком экране действия уходят под текст.
 *
 * Заголовок, подзаголовок и кнопка приходят из CMS; если раздел не
 * заполнен, показываются значения по умолчанию.
 */

import type { HomeContent } from '@oinau/api-types';

import { QuickOrderButton } from '@/components/quick-order/QuickOrderButton';
import { ButtonLink } from '@/components/ui/Button';
import styles from './Hero.module.css';

const DEFAULT_TITLE = 'Комплектующие для современных площадок';
const DEFAULT_SUBTITLE =
  'Канаты, крепёж, сиденья, горки и готовые узлы со склада в Алматы — для производителей, ' +
  'монтажных организаций и муниципальных проектов.';

/** Якорь секции разделов ниже hero. */
export const SOLUTIONS_ANCHOR = 'solutions';

/**
 * Акцент — предпоследнее слово заголовка: «Комплектующие для
 * <современных> площадок». Разбивать по фиксированному индексу нельзя:
 * текст редактируется в CMS.
 */
export function splitTitle(title: string): { head: string; accent: string; tail: string } {
  const words = title.trim().split(/\s+/);
  if (words.length < 3) return { head: title.trim(), accent: '', tail: '' };
  return {
    head: words.slice(0, -2).join(' '),
    accent: words[words.length - 2] ?? '',
    tail: words[words.length - 1] ?? '',
  };
}

export function Hero({ content }: { content: HomeContent | null }) {
  const hero = content?.hero;
  const { head, accent, tail } = splitTitle(hero?.title || DEFAULT_TITLE);
  const subtitle = hero?.subtitle || DEFAULT_SUBTITLE;
  const ctaLabel = hero?.cta_label || 'Перейти в каталог';
  const ctaUrl = hero?.cta_url || '/catalog';

  return (
    <section className={`container ${styles.hero}`} aria-labelledby="hero-title">
      <div className={styles.lead}>
        <div className={styles.text}>
          <p className={styles.eyebrow}>ГОСТ Р 52168 · ЕАЭС</p>
          <h1 className={styles.title} id="hero-title">
            {accent ? (
              <>
                {head} <span className={styles.titleAccent}>{accent}</span> {tail}
              </>
            ) : (
              head
            )}
          </h1>
          <p className={styles.subtitle}>{subtitle}</p>
        </div>

        <div className={styles.actions}>
          <QuickOrderButton variant="light" size="lg">
            Быстрый заказ
          </QuickOrderButton>
          <ButtonLink href={ctaUrl} variant="onDark" size="lg">
            {ctaLabel}
          </ButtonLink>
        </div>
      </div>
    </section>
  );
}
