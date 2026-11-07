// Build-time sitemap generator.
//
// Pulls every professor slug and course code from the live API and writes
// public/sitemap.xml so crawlers (and AI engines) can discover every page.
// Runs as part of `npm run build` (see package.json prebuild). It degrades
// gracefully: if the API is unreachable it still writes a sitemap with the
// static routes so the build never fails on a transient network blip.

import { writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT = join(__dirname, '..', 'public', 'sitemap.xml');

const SITE = process.env.SITE_URL || 'https://ratemyhusky.com';
const API = process.env.SITEMAP_API_URL || 'https://ratemyhusky.com';

// Static, always-present routes. `priority` is a hint, not a ranking lever.
const STATIC_ROUTES = [
  { path: '/', priority: '1.0', changefreq: 'daily' },
  { path: '/professors', priority: '0.9', changefreq: 'daily' },
  { path: '/courses', priority: '0.9', changefreq: 'daily' },
  { path: '/compare', priority: '0.5', changefreq: 'weekly' },
  { path: '/departments', priority: '0.7', changefreq: 'weekly' },
  { path: '/faq', priority: '0.5', changefreq: 'monthly' },
];

async function fetchAll(endpoint, key) {
  // Catalog endpoints accept a large limit and return { [key]: [...] }.
  const url = `${API}/api/${endpoint}?limit=10000&page=1`;
  const proxyKey = process.env.SITEMAP_PROXY_KEY;
  const headers = proxyKey ? { 'x-proxy-key': proxyKey } : undefined;
  const res = await fetch(url, { headers });
  if (!res.ok) throw new Error(`${endpoint} -> HTTP ${res.status}`);
  const data = await res.json();
  return Array.isArray(data[key]) ? data[key] : [];
}

// No <lastmod>: the API has no per-page update time, and a build date on every URL
// teaches search engines to ignore the field.
function xmlUrl({ loc, changefreq, priority }) {
  return [
    '  <url>',
    `    <loc>${loc}</loc>`,
    changefreq ? `    <changefreq>${changefreq}</changefreq>` : null,
    priority ? `    <priority>${priority}</priority>` : null,
    '  </url>',
  ].filter(Boolean).join('\n');
}

function esc(s) {
  return String(s).replace(/[<>&'"]/g, (c) =>
    ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', "'": '&apos;', '"': '&quot;' }[c]));
}

async function main() {
  const urls = STATIC_ROUTES.map((r) =>
    xmlUrl({ loc: `${SITE}${r.path}`, changefreq: r.changefreq, priority: r.priority }));

  let profCount = 0;
  let courseCount = 0;

  try {
    const professors = await fetchAll('professors-catalog', 'professors');
    for (const p of professors) {
      if (!p.slug) continue;
      urls.push(xmlUrl({ loc: `${SITE}/professors/${esc(p.slug)}`, changefreq: 'weekly', priority: '0.7' }));
      profCount++;
    }
  } catch (e) {
    console.warn(`[sitemap] could not fetch professors: ${e.message}`);
  }

  try {
    const courses = await fetchAll('courses-catalog', 'courses');
    for (const c of courses) {
      if (!c.code) continue;
      urls.push(xmlUrl({ loc: `${SITE}/courses/${esc(c.code)}`, changefreq: 'weekly', priority: '0.6' }));
      courseCount++;
    }
  } catch (e) {
    console.warn(`[sitemap] could not fetch courses: ${e.message}`);
  }

  try {
    const departments = await fetchAll('departments/hub', 'departments');
    for (const d of departments) {
      if (!d.slug) continue;
      urls.push(xmlUrl({ loc: `${SITE}/departments/${esc(d.slug)}`, changefreq: 'weekly', priority: '0.6' }));
    }
  } catch (e) {
    console.warn(`[sitemap] could not fetch departments: ${e.message}`);
  }

  if (profCount === 0 && courseCount === 0) {
    console.warn('[sitemap] both fetches returned nothing; keeping the committed sitemap.xml untouched');
    return;
  }

  const xml =
    '<?xml version="1.0" encoding="UTF-8"?>\n' +
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
    urls.join('\n') +
    '\n</urlset>\n';

  await writeFile(OUT, xml, 'utf8');
  console.log(`[sitemap] wrote ${urls.length} urls (${profCount} professors, ${courseCount} courses) -> public/sitemap.xml`);
}

main().catch((e) => {
  // Never fail the build over the sitemap.
  console.warn(`[sitemap] generation failed: ${e.message}`);
});
