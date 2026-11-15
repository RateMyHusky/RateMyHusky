import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

// Chrome loads files by name, so no hashed filenames. public/ is copied into
// dist as-is, which covers manifest.json and any icons.
const manifest = fileURLToPath(new URL('./public/manifest.json', import.meta.url));

export default defineConfig(({ mode }) => ({
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
    // Production builds start clean. Under `npm run dev` this pass rebuilds on
    // every popup edit, and emptying dist each time deleted the content
    // script the other watcher (dev:content) had built — whose own sources
    // hadn't changed, so it never rebuilt, and Banner's badges stopped with no
    // error anywhere.
    emptyOutDir: mode !== 'development',
    rollupOptions: {
      input: {
        index: fileURLToPath(new URL('./index.html', import.meta.url)),
        // The service worker ships as a module, so it can come through this
        // pass with the popup. The content script can't — see
        // vite.content.config.ts for why it gets its own.
        background: fileURLToPath(new URL('./src/banner/background.ts', import.meta.url)),
      },
      output: {
        entryFileNames: '[name].js',
        chunkFileNames: '[name].js',
        assetFileNames: '[name].[ext]',
      },
    },
  },
}));
