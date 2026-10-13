/**
 * Главный экран.
 *
 * Заголовок, подзаголовок и кнопка приходят из CMS; если раздел не
 * заполнен, показываются осмысленные значения по умолчанию — сайт
 * должен открываться и на пустой базе.
 *
 * Показатели под кнопками считаются по каталогу (число позиций), а не
 * выдумываются: цифра на главной обязана сходиться с каталогом.
 *
 * Текст и фотография лежат в двух колонках сетки. Наложение слоёв здесь
 * недопустимо: текстовый слой во всю ширину перекрывал бы фотографию
 * и делал метки на ней ненажимаемыми.
 */

import Image from 'next/image';

import type { HomeContent } from '@oinau/api-types';

import { ButtonLink } from '@/components/ui/Button';
import { formatCount } from '@/lib/format';
import type { ResolvedHotspot } from '@/lib/hotspots';
import { PlaygroundHotspots, PlaygroundHotspotsList } from './PlaygroundHotspots';
import styles from './Hero.module.css';

const DEFAULT_TITLE = 'Комплектующие для площадок, которые служат годами';
const DEFAULT_SUBTITLE =
  'Канаты, крепёж, сиденья, втулки, горки и готовые узлы. Для производителей, ' +
  'монтажных организаций и муниципальных проектов Казахстана.';

/**
 * Последние два слова заголовка подсвечиваются — так в макете.
 * Разбивать по фиксированному индексу нельзя: текст редактируется в CMS.
 */
function splitTitle(title: string): [string, string] {
  const words = title.trim().split(/\s+/);
  if (words.length < 4) return [title, ''];
  return [words.slice(0, -2).join(' '), words.slice(-2).join(' ')];
}

export function Hero({
  content,
  hotspots,
  totalProducts,
  categoriesCount,
}: {
  content: HomeContent | null;
  hotspots: ResolvedHotspot[];
  totalProducts: number;
  categoriesCount: number;
}) {
  const hero = content?.hero;
  const [head, accent] = splitTitle(hero?.title ?? DEFAULT_TITLE);
  const subtitle = hero?.subtitle ?? DEFAULT_SUBTITLE;
  const ctaLabel = hero?.cta_label ?? 'Открыть каталог';
  const ctaUrl = hero?.cta_url ?? '/catalog';

  return (
    <section className={styles.hero} aria-labelledby="hero-title">
      <div className={styles.inner}>
        <div className={styles.copy}>
          <p className={styles.eyebrow}>Сертификаты ЕАЭС · ГОСТ Р 52168</p>

          <h1 className={styles.title} id="hero-title">
            {head} {accent ? <span className={styles.titleAccent}>{accent}</span> : null}
          </h1>

          <p className={styles.subtitle}>{subtitle}</p>

          <div className={styles.actions}>
            <ButtonLink href={ctaUrl} size="lg">
              {ctaLabel} →
            </ButtonLink>
            <ButtonLink href="/contacts" size="lg" variant="onDark">
              Запросить оптовый прайс
            </ButtonLink>
          </div>

          {/* Подпись в разметке идёт первой (иначе <dl> невалиден),
              а визуально её опускает под значение column-reverse. */}
          <dl className={styles.stats}>
            <div className={styles.stat}>
              <dt className={styles.statLabel}>позиций в каталоге</dt>
              <dd className={styles.statValue}>{formatCount(totalProducts)}</dd>
            </div>
            <div className={styles.stat}>
              <dt className={styles.statLabel}>разделов комплектующих</dt>
              <dd className={styles.statValue}>{formatCount(categoriesCount)}</dd>
            </div>
            <div className={styles.stat}>
              <dt className={styles.statLabel}>отгрузка по Алматы</dt>
              <dd className={styles.statValue}>24 ч</dd>
            </div>
          </dl>

          <p className={styles.hint}>
            <span className={styles.hintDot} aria-hidden="true" />
            Нажмите на узел — откроется его комплектация
          </p>
        </div>

        <div className={styles.media}>
          {/* Маска растворения краёв — на отдельной обёртке снимка:
              плашки лежат рядом, а не внутри, и не выцветают вместе с краем. */}
          <div className={styles.photo}>
            <Image
              // Изображение из макета — часть оформления сайта, а не
              // карточка товара, поэтому лежит в public, а не в медиатеке.
              src="/brand/playground.webp"
              alt="Смонтированная детская площадка: игровой комплекс, качели, горка и канатные элементы"
              fill
              priority
              sizes="(max-width: 1180px) 100vw, min(1180px, 68vw)"
              className={styles.image}
            />
          </div>
          <PlaygroundHotspots hotspots={hotspots} />
        </div>
      </div>

      <PlaygroundHotspotsList hotspots={hotspots} />
    </section>
  );
}
