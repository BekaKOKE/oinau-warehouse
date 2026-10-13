import { ButtonLink } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/States';
import styles from '@/components/content/Page.module.css';

export default function NotFound() {
  return (
    <div className={`container ${styles.page}`}>
      <header className={styles.header}>
        <h1 className={styles.title}>Страница не найдена</h1>
        <p className={styles.lead}>
          Возможно, позиция снята с производства или адрес набран с ошибкой. Найдите нужное в
          каталоге или через поиск по артикулу.
        </p>
      </header>

      <section className={styles.section}>
        <EmptyState
          title="404 — такой страницы нет"
          text="Проверьте адрес или начните с каталога комплектующих."
          action={
            <>
              <ButtonLink href="/catalog">Перейти в каталог</ButtonLink>
              <ButtonLink href="/contacts" variant="outline">
                Связаться с нами
              </ButtonLink>
            </>
          }
        />
      </section>
    </div>
  );
}
