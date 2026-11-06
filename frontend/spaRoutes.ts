// Route knowledge for the middleware's crawler 404 (pure, so it can be selftested).
// Run the selftest: cd frontend && npm run test:routes

import { RATE_ENABLED } from './src/config';

// Top-level paths of the routes in src/App.tsx. The selftest fails if App.tsx has a route
// this list doesn't cover.
const SPA_ROUTES = ['professors', 'courses', 'departments', 'compare', 'bookmarks',
  ...(RATE_ENABLED ? ['rate'] : []), 'account', 'account/bookmarks', 'terms', 'privacy', 'faq'];
const SPA_ROUTE_RE = new RegExp(`^/(${SPA_ROUTES.join('|')})?/?$`, 'i');

// Matches /professors/<slug>, /courses/<code>, and /departments/<slug> (single trailing segment).
// Case-sensitive: the middleware uses it to pick backend snapshots.
export const DETAIL_RE = /^\/(professors|courses|departments)\/([^/]+)\/?$/;
// Case-insensitive like the router.
const ANY_DETAIL_RE = new RegExp(DETAIL_RE.source, 'i');

export function isUnknownRoute(pathname: string): boolean {
  if (SPA_ROUTE_RE.test(pathname) || ANY_DETAIL_RE.test(pathname)) return false;
  const last = pathname.slice(pathname.lastIndexOf('/') + 1);
  return !last.includes('.');
}

const NOT_FOUND_HTML = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="robots" content="noindex">
<title>Not found | RateMyHusky</title>
</head>
<body>
<h1>Page not found</h1>
<p><a href="/">Back to homepage</a></p>
</body>
</html>`;

export function notFoundPage(): Response {
  return new Response(NOT_FOUND_HTML, {
    status: 404,
    headers: {
      'content-type': 'text/html; charset=utf-8',
      // Only crawlers get this page, so no shared cache may hand it to a browser.
      'cache-control': 'private, max-age=3600',
      'x-crawler-404': '1',
    },
  });
}
