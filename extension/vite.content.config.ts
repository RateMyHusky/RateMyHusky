import { defineConfig } from 'vite';
import { fileURLToPath } from 'node:url';

/** Second build pass, for the content script alone.
 *
 *  MV3 content scripts can't be ES modules and the popup pass emits ESM, so
 *  the content script needs its own build in IIFE format. Getting this wrong
 *  fails silently: the script is installed, Chrome reports no error, and it
 *  simply never runs.
 *
 *  IIFE rules out code splitting, so everything content.ts imports is inlined
 *  into content.js. Keep its imports to ./messages and whatever step 8 needs —
 *  pulling in React or api.ts here would ship the popup twice. */
export default defineConfig({
  build: {
    outDir: 'dist',
    // The popup pass already emptied dist; emptying it again would delete it.
    emptyOutDir: false,
    lib: {
      entry: fileURLToPath(new URL('./src/banner/content.ts', import.meta.url)),
      formats: ['iife'],
      name: 'RateMyHuskyBanner',
      fileName: () => 'content.js',
    },
    rollupOptions: {
      // Named, not hashed: registerContentScripts refers to these by path.
      output: { assetFileNames: 'content.[ext]' },
    },
  },
});
