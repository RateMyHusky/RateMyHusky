// Post-build check, run in CI after `npm run build`.
// - Every inline script in dist/index.html must have its sha256 in the CSP
//   script-src in vercel.json, or browsers report (and, once enforced, block) it.
// - Both built pages must keep the GA real_visit / automated_browser tags, with
//   the user property set before config so the first page view carries it.
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';

const read = (p) => readFileSync(new URL(`../${p}`, import.meta.url), 'utf8').replace(/\r\n/g, '\n');
const inlineScripts = (html) =>
  [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1]);

const csp = JSON.parse(read('vercel.json'))
  .headers.flatMap((h) => h.headers)
  .find((h) => h.key.startsWith('Content-Security-Policy')).value;

const errors = [];
for (const page of ['dist/index.html', 'dist/maintenance.html']) {
  const scripts = inlineScripts(read(page));
  if (page === 'dist/index.html') {
    for (const s of scripts) {
      const hash = `'sha256-${createHash('sha256').update(s).digest('base64')}'`;
      if (!csp.includes(hash)) errors.push(`${page}: inline script ${hash} is not in the vercel.json CSP`);
    }
  }
  const ga = scripts.find((s) => s.includes("gtag('config'"));
  if (!ga) {
    errors.push(`${page}: no inline gtag config script`);
    continue;
  }
  if (!ga.includes("gtag('event', 'real_visit')")) errors.push(`${page}: real_visit event missing`);
  const setAt = ga.indexOf('automated_browser');
  if (setAt < 0 || setAt > ga.indexOf("gtag('config'")) {
    errors.push(`${page}: automated_browser must be set before gtag config`);
  }
}

if (errors.length) {
  console.error(errors.join('\n'));
  process.exit(1);
}
console.log('Inline scripts match the CSP and keep the GA tags.');
