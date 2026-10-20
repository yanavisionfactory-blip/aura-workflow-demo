import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import { fileURLToPath, URL } from 'node:url';
import { showcaseAliases } from './src/showcase/weekly-account-review/buildAliases.mjs';

export default defineConfig({
  root: fileURLToPath(new URL('./showcase/weekly-account-review', import.meta.url)),
  base: './',
  publicDir: false,
  resolve: { alias: [...showcaseAliases, { find: '@', replacement: fileURLToPath(new URL('./src', import.meta.url)) }] },
  plugins: [react(), {
    name: 'exclude-live-account-clients',
    generateBundle(_options, bundle) {
      for (const item of Object.values(bundle)) {
        if (item.type !== 'chunk') continue;
        const forbidden = Object.keys(item.modules).filter((id) => /\/src\/api\/|\/src\/lib\/auraApi\.|\/@clerk\/|\/@base44\/sdk\//.test(id));
        if (forbidden.length) this.error(`Live account modules cannot ship in the public demo: ${forbidden.join(', ')}`);
      }
    },
  }],
  build: {
    outDir: fileURLToPath(new URL('./dist/showcase/weekly-account-review', import.meta.url)),
    emptyOutDir: true,
    sourcemap: false,
  },
});
