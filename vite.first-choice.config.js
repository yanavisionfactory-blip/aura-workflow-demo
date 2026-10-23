import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import { fileURLToPath, URL } from 'node:url';
import { showcaseAliases } from './src/showcase/website-content/buildAliases.mjs';

export default defineConfig({
  root: fileURLToPath(new URL('./showcase/first-choice-seo', import.meta.url)),
  base: './',
  publicDir: fileURLToPath(new URL('./showcase/first-choice-seo/public', import.meta.url)),
  resolve: { alias: [{find:'./ConnectionsPill',replacement:fileURLToPath(new URL('./src/showcase/first-choice-seo/Resources.jsx',import.meta.url))}, ...showcaseAliases, { find: '@', replacement: fileURLToPath(new URL('./src', import.meta.url)) }] },
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
    outDir: fileURLToPath(new URL('./dist/showcase/first-choice-seo', import.meta.url)),
    emptyOutDir: true,
    sourcemap: false,
  },
});
