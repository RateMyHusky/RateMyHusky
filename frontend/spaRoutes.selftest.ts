// Runnable self-check for spaRoutes (no unit-test framework is installed).
// Run: cd frontend && npm run test:routes (CI runs it too)
// Prints PASS/FAIL per check and exits non-zero on any failure.
import { readFileSync } from 'node:fs';
import { isUnknownRoute, notFoundPage } from './spaRoutes';
import { RATE_ENABLED } from './src/config';

const fails: string[] = [];
const check = (label: string, cond: boolean) => {
  if (!cond) fails.push(label);
  console.log((cond ? 'PASS' : 'FAIL') + ': ' + label);
};

for (const p of ['/', '/professors', '/professors/', '/courses', '/departments', '/compare',
  '/bookmarks', '/account', '/account/bookmarks', '/terms', '/privacy', '/faq', '/faq/',
  '/FAQ', '/Compare/', '/professors/patrick-hurley', '/courses/cs3000', '/departments/khoury',
  '/Professors/alan-mislove', '/professors/a%2Fb', '/professors/x/',
  '/assets/index-abc123.js', '/logo.jpg', '/index.html', '/ratemyhusky.png',
  '/.well-known/security.txt', '/a/b/c.css'])
  check(`known: ${p}`, isUnknownRoute(p) === false);
for (const p of ['/asdf', '/privacy/x', '/professors/a/b', '/courses/cs3000/reviews',
  '/compare/x', '/account/x', '//asdf', '/bypass-redeem'])
  check(`unknown: ${p}`, isUnknownRoute(p) === true);
check(`/rate known iff RATE_ENABLED (${RATE_ENABLED})`, isUnknownRoute('/rate') === !RATE_ENABLED);

// Every route in App.tsx must be known, or crawlers get a 404 for it. Flag-gated routes
// count only while their flag is on.
const appRoutes = [...readFileSync(new URL('./src/App.tsx', import.meta.url), 'utf8')
  .matchAll(/^.*<Route path="([^"]+)".*$/gm)];
check('App.tsx routes found', appRoutes.length >= 10);
for (const [line, path] of appRoutes) {
  if (path === '*') continue;
  const live = !line.includes('RATE_ENABLED &&') || RATE_ENABLED;
  check(`App.tsx route ${path}`, isUnknownRoute(path.replace(/:\w+/g, 'x')) === !live);
}

const res = notFoundPage();
check('status 404', res.status === 404);
check('content-type', res.headers.get('content-type') === 'text/html; charset=utf-8');
check('cache-control', res.headers.get('cache-control') === 'private, max-age=3600');
check('x-crawler-404', res.headers.get('x-crawler-404') === '1');
const html = await res.text();
check('noindex', html.includes('<meta name="robots" content="noindex">'));
check('title', html.includes('<title>Not found | RateMyHusky</title>'));
check('home link', html.includes('href="/"'));

console.log(fails.length ? `\n${fails.length} FAILED` : '\nall passed');
process.exit(fails.length ? 1 : 0);
