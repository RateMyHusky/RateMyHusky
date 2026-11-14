import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

// Chrome loads files by name, so no hashed filenames. public/ is copied into
// dist as-is, which covers manifest.json and any icons.
const manifest = fileURLToPath(new URL('./public/manifest.json', import.meta.url));

export default defineConfig({
  plugins: [
    react(),
    {
      // public/ is copied but not watched, so `vite build --watch` would leave
      // a stale manifest in dist after an edit. Resolved from this file rather
      // than cwd, so building from the repo root works too.
      name: 'watch-manifest',
      buildStart() {
        this.addWatchFile(manifest);
      },
    },
  ],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        popup: resolve(import.meta.dirname, 'index.html'),
        background: resolve(import.meta.dirname, 'src/background.ts'),
      },
      output: {
        entryFileNames: '[name].js',
        chunkFileNames: '[name].js',
        assetFileNames: '[name].[ext]',
      },
    },
  },
});
