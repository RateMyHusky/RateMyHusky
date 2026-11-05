// Route knowledge for the middleware's crawler 404 (pure, so it can be selftested).
// Run the selftest: cd frontend && npx tsx spaRoutes.selftest.ts

// Keep in sync with the routes in src/App.tsx.
const SPA_ROUTE_RE = /^\/(professors|courses|departments|compare|bookmarks|rate|account|account\/bookmarks|terms|privacy|faq)?\/?$/i;
// Case-insensitive like the router (middleware's DETAIL_RE is case-sensitive, for snapshots).
const ANY_DETAIL_RE = /^\/(professors|courses|departments)\/[^/]+\/?$/i;

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
      'cache-control': 'public, max-age=3600',
      'x-prerendered': '1',
    },
  });
}
