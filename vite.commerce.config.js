import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import { fileURLToPath, URL } from 'node:url';

export default defineConfig({
  root: fileURLToPath(new URL('./showcase/commerce-workflow', import.meta.url)),
  base: './', publicDir: false,
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  plugins: [react(), { name: 'exclude-live-clients-from-commerce-simulation', generateBundle(_options, bundle) {
    for (const item of Object.values(bundle)) if (item.type === 'chunk') {
      const forbidden = Object.keys(item.modules).filter(id => /\/src\/api\/|\/src\/lib\/auraApi\.|\/@clerk\/|\/@base44\/sdk\//.test(id));
      if (forbidden.length) this.error(`Live account clients cannot ship in this simulation: ${forbidden.join(', ')}`);
    }
  } }],
  build: { outDir: fileURLToPath(new URL('./dist/showcase/commerce-workflow', import.meta.url)), emptyOutDir: true, sourcemap: false },
});
