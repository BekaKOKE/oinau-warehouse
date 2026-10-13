import { fileURLToPath } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// Расширение .mts: без него Vitest грузит конфиг как CommonJS,
// а плагины Vite поставляются только в ESM.
export default defineConfig({
  plugins: [react()],
  resolve: {
    // Тот же алиас, что в tsconfig.json.
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    include: ['tests/**/*.test.{ts,tsx}'],
    css: {
      modules: { classNameStrategy: 'non-scoped' },
    },
  },
});
