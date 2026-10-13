import Link from 'next/link';

export default function NotFound() {
  return (
    <main style={{ display: 'grid', placeItems: 'center', minHeight: '100vh', padding: 24 }}>
      <div style={{ textAlign: 'center' }}>
        <p style={{ fontSize: 48, fontWeight: 700, color: 'var(--text-faint)' }}>404</p>
        <h1 style={{ fontSize: 20, marginTop: 8 }}>Страница не найдена</h1>
        <p style={{ marginTop: 8, color: 'var(--text-muted)' }}>
          Адрес устарел или набран с ошибкой.
        </p>
        <p style={{ marginTop: 16 }}>
          <Link href="/">На главную панели</Link>
        </p>
      </div>
    </main>
  );
}
