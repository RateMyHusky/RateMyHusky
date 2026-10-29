// Vercel Routing Middleware: maintenance gate + authenticated API proxy.
//
// - While maintenance.config.json has "on": true (stamped by maintenance.py),
//   every request without a valid signed bypass cookie is 307'd to
//   /maintenance.html — same semantics the page's auto-recovery poll and the
//   SPA's maintenanceGuard() rely on.
// - Preview deploys (VERCEL_ENV=preview) are always gated the same way, so
//   only bypass holders can see them; the page shows dev-preview copy there.
// - /bypass-handoff + /bypass-redeem copy a ratemyhusky.com bypass cookie
//   over to a preview deploy, which can't read it across domains (see the
//   handlers below).
// - /api/* is proxied to Railway with the x-proxy-key header so the backend
//   can reject traffic that didn't come through Vercel.
//
// Env vars (set in Vercel project settings):
//   RAILWAY_ORIGIN    — backend origin, e.g. https://xyz.up.railway.app
//   MAINT_SIGNING_KEY — HMAC key for bypass tokens (mint: maintenance.py -invite).
//                       Preview must use the same value as Production, or
//                       every handoff fails to redeem and lands on handoff=none.
//   PROXY_SECRET      — shared secret the backend checks; also set on Railway

import maintenance from './maintenance.config.json';

// Share of CSP violation reports forwarded to the backend's /api/csp-report.
const CSP_REPORT_SAMPLE = 0.1;

// Skip the maintenance page itself, the assets it needs, crawler/AdSense
// files, Vercel internals (analytics beacons, etc.), and professor photo
// thumbnails (a catalog page loads dozens; each would be a middleware call).
export const config = {
  matcher:
    '/((?!maintenance\\.html|logo\\.jpg|neu-husky-icon\\.png|robots\\.txt|ads\\.txt|sitemap\\.xml|llms\\.txt|2c426a030622417e4b03f2011ae5959e\\.txt|_vercel|photos/).*)',
};

// Preview hosts /bypass-handoff will redirect to. Not the security boundary
// (anyone can claim a free *.vercel.app alias): handoff codes are bound to
// their target origin and only redeemable there, so a code sent to a
// look-alike host is useless. That host does still see the bypass name and
// expiry inside the code.
const PREVIEW_ORIGIN_RE = /^https:\/\/rate-my-husky-(?:git-[a-z0-9-]+|[a-z0-9]+)-grain-is-grainys-projects\.vercel\.app$/;
const HANDOFF_TTL_SECONDS = 60;

async function hmacHex(key: string, message: string): Promise<string> {
  const enc = new TextEncoder();
  const cryptoKey = await crypto.subtle.importKey(
    'raw', enc.encode(key), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'],
  );
  const mac = await crypto.subtle.sign('HMAC', cryptoKey, enc.encode(message));
  return Array.from(new Uint8Array(mac), b => b.toString(16).padStart(2, '0')).join('');
}

function safeEqual(expected: string, actual: string): boolean {
  if (expected.length !== actual.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i++) {
    diff |= expected.charCodeAt(i) ^ actual.charCodeAt(i);
  }
  return diff === 0;
}

function isFuture(epochSeconds: string): boolean {
  return /^\d+$/.test(epochSeconds) && Number(epochSeconds) >= Date.now() / 1000;
}

// Bypass token: "<name>.<expiry-epoch-seconds>.<hex hmac-sha256 of "name.expiry">"
// A preview also accepts the token /bypass-redeem sets there, which signs
// "preview|<origin>|name.expiry" so it only works on that one preview.
// Returns [name, expiry] when the request carries a valid one.
async function validBypass(request: Request): Promise<[string, string] | null> {
  const key = process.env.MAINT_SIGNING_KEY;
  if (!key) return null;

  const cookies = request.headers.get('cookie') || '';
  const match = cookies.match(/(?:^|;\s*)rmh_dev=([^;]+)/);
  if (!match) return null;

  const parts = match[1].split('.');
  if (parts.length !== 3) return null;
  const [name, expStr, sig] = parts;
  if (!isFuture(expStr)) return null;

  if (safeEqual(await hmacHex(key, `${name}.${expStr}`), sig)) return [name, expStr];
  if (process.env.VERCEL_ENV === 'preview' &&
      safeEqual(await hmacHex(key, `preview|${new URL(request.url).origin}|${name}.${expStr}`), sig)) {
    return [name, expStr];
  }
  return null;
}

// Handoff code: "<name>.<expiry>.<code-expiry>.<hmac of handoff|origin|name.expiry|code-expiry>".
// Reusable until it expires, so a leaked one (e.g. from request logs) opens
// only its own preview for up to HANDOFF_TTL_SECONDS, never the live site.
async function mintHandoffCode(key: string, origin: string, name: string, exp: string): Promise<string> {
  const codeExp = String(Math.floor(Date.now() / 1000) + HANDOFF_TTL_SECONDS);
  const sig = await hmacHex(key, `handoff|${origin}|${name}.${exp}|${codeExp}`);
  return `${name}.${exp}.${codeExp}.${sig}`;
}

// Returns the origin-scoped bypass token to set as this origin's cookie, or null.
async function redeemHandoffCode(key: string, origin: string, code: string): Promise<string | null> {
  const parts = code.split('.');
  if (parts.length !== 4) return null;
  const [name, exp, codeExp, sig] = parts;
  if (!isFuture(exp) || !isFuture(codeExp)) return null;
  if (!safeEqual(await hmacHex(key, `handoff|${origin}|${name}.${exp}|${codeExp}`), sig)) return null;
  return `${name}.${exp}.${await hmacHex(key, `preview|${origin}|${name}.${exp}`)}`;
}

// Where /bypass-redeem lands: ?next= if it stays on this origin, else /.
// Returns an absolute URL, since a bare path like "//evil.com" would leave.
function sameOriginNext(next: string | null, origin: string): string {
  try {
    const dest = new URL(next || '/', origin);
    if (dest.origin === origin) return dest.href;
  } catch { /* malformed next */ }
  return `${origin}/`;
}

async function proxyToBackend(request: Request, url: URL): Promise<Response> {
  const origin = process.env.RAILWAY_ORIGIN;
  if (!origin) {
    return new Response(
      JSON.stringify({ error: 'RAILWAY_ORIGIN is not configured' }),
      { status: 503, headers: { 'content-type': 'application/json' } },
    );
  }
  const target = new URL(url.pathname + url.search, origin);

  const headers = new Headers(request.headers);
  headers.delete('host');
  headers.delete('content-length');
  const proxyKey = process.env.PROXY_SECRET;
  if (proxyKey) headers.set('x-proxy-key', proxyKey);
  // Railway appends the Vercel edge's own address to X-Forwarded-For, so the
  // last entry is Vercel, not the student. Vercel overwrites x-real-ip, so
  // pass it on as the one client IP the backend trusts; drop any client copy.
  // No Cloudflare sits in front of us, so a CF-Connecting-IP is always client-sent.
  headers.delete('x-rmh-client-ip');
  headers.delete('cf-connecting-ip');
  const clientIp = request.headers.get('x-real-ip');
  if (clientIp) headers.set('x-rmh-client-ip', clientIp);

  const hasBody = request.method !== 'GET' && request.method !== 'HEAD';
  return fetch(target, {
    method: request.method,
    headers,
    body: hasBody ? await request.arrayBuffer() : undefined,
    // Pass 3xx (e.g. the Google OAuth redirect) through to the browser.
    redirect: 'manual',
  });
}

const CRAWLER_UAS = [
  // Search & AI crawlers
  'googlebot', 'google-inspectiontool', 'google-extended', 'bingbot', 'gptbot', 'oai-searchbot',
  'chatgpt-user', 'claudebot', 'claude-searchbot', 'claude-user',
  'anthropic-ai', 'perplexitybot', 'perplexity-user', 'applebot',
  // Social link-preview scrapers (none run JS, so they need the snapshot
  // to get a rich preview with title/description/image)
  'facebookexternalhit', 'facebookcatalog', 'twitterbot', 'slackbot',
  'slack-imgproxy', 'discordbot', 'linkedinbot', 'whatsapp', 'telegrambot',
  'pinterest', 'redditbot', 'skypeuripreview', 'vkshare', 'embedly',
  'iframely', 'mastodon', 'bsky',
  // Google AI fetcher + AdSense content crawlers (none run JS)
  'googleother', 'google-cloudvertexbot', 'mediapartners-google', 'adsbot-google',
];

function isCrawler(ua: string): boolean {
  const lc = ua.toLowerCase();
  return CRAWLER_UAS.some((bot) => lc.includes(bot));
}

// Matches /professors/<slug>, /courses/<code>, and /departments/<slug> (single trailing segment).
const DETAIL_RE = /^\/(professors|courses|departments)\/([^/]+)\/?$/;

// Exact non-detail paths that get a server-rendered snapshot for crawlers.
const STATIC_RENDER: Record<string, string> = {
  '/': '/render/home',
  '/professors': '/render/professors',
  '/courses': '/render/courses',
  '/departments': '/render/departments',
};

// Headers for a snapshot fetch: the proxy key, and the crawler's IP so the backend
// rate-limits each crawler on its own rather than all of them as Vercel's address.
function snapshotHeaders(clientIp: string | null): Headers {
  const headers = new Headers();
  const proxyKey = process.env.PROXY_SECRET;
  if (proxyKey) headers.set('x-proxy-key', proxyKey);
  if (clientIp) headers.set('x-rmh-client-ip', clientIp);
  return headers;
}

async function fetchSnapshot(pathname: string, clientIp: string | null): Promise<Response | undefined> {
  const origin = process.env.RAILWAY_ORIGIN;
  if (!origin) return undefined;

  // Exact-match home/listing routes (no slug → no SSRF decoding needed).
  const staticTarget = STATIC_RENDER[pathname];
  if (staticTarget) {
    const headers = snapshotHeaders(clientIp);
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 4000);
      const res = await fetch(new URL(staticTarget, origin), {
        headers, signal: controller.signal,
      });
      clearTimeout(timer);
      if (!res.ok && res.status !== 404) return undefined;
      return res;
    } catch {
      return undefined;
    }
  }

  const m = pathname.match(DETAIL_RE);
  if (!m) return undefined;
  const slug = m[2];
  // Reject encoded slashes / traversal so the slug can't escape the
  // /render/<kind>/ path segment (edge-to-origin SSRF hardening).
  let decoded = slug;
  try {
    decoded = decodeURIComponent(slug);
    // one more pass to catch double-encoding
    decoded = decodeURIComponent(decoded);
  } catch {
    return undefined; // malformed percent-encoding
  }
  if (/[/\\]/.test(decoded) || decoded.includes('..')) {
    return undefined;
  }
  const kind = m[1] === 'professors' ? 'professors' : m[1] === 'courses' ? 'courses' : 'departments';
  const target = new URL(`/render/${kind}/${slug}`, origin);
  const headers = snapshotHeaders(clientIp);
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 4000);
    const res = await fetch(target, { headers, signal: controller.signal });
    clearTimeout(timer);
    if (!res.ok && res.status !== 404) return undefined; // fall back to SPA on 5xx
    return res;
  } catch {
    return undefined; // any failure → SPA fallback
  }
}

export default async function middleware(request: Request): Promise<Response | undefined> {
  const url = new URL(request.url);

  // Both handoff routes run before the maintenance gate so they work while
  // the site is down too.
  const key = process.env.MAINT_SIGNING_KEY;
  const isPreview = process.env.VERCEL_ENV === 'preview';

  // A preview's gate page sends the browser here (on ratemyhusky.com) with
  // ?to=<preview origin>. If it already holds a valid bypass cookie, bounce
  // back to that preview's /bypass-redeem with a short-lived code bound to
  // it (passing ?next= along); otherwise bounce back to its gate page with
  // handoff=none. Not served on previews: there validBypass also accepts a
  // preview-scoped cookie, which would let it mint codes for other previews.
  if (url.pathname === '/bypass-handoff' && !isPreview) {
    const to = url.searchParams.get('to') || '';
    if (!PREVIEW_ORIGIN_RE.test(to)) {
      return new Response('Invalid handoff target', { status: 400 });
    }
    const bypass = await validBypass(request);
    const next = url.searchParams.get('next');
    const nextParam = next ? `&next=${encodeURIComponent(next)}` : '';
    const location = key && bypass
      ? `${to}/bypass-redeem?code=${await mintHandoffCode(key, to, ...bypass)}${nextParam}`
      : `${to}/maintenance.html?mode=preview&handoff=none${nextParam}`;
    return new Response(null, {
      status: 302,
      headers: { Location: location, 'cache-control': 'no-store' },
    });
  }

  // On the preview: trade a handoff code minted for this origin for this
  // origin's own bypass cookie, then land on the page that was gated.
  if (url.pathname === '/bypass-redeem') {
    const token = key && await redeemHandoffCode(key, url.origin, url.searchParams.get('code') || '');
    const next = url.searchParams.get('next');
    const headers = new Headers({ 'cache-control': 'no-store' });
    if (token) {
      headers.set('Location', sameOriginNext(next, url.origin));
      headers.set('Set-Cookie', `rmh_dev=${token}; Path=/; Max-Age=2592000; SameSite=Lax; Secure`);
    } else {
      headers.set('Location', '/maintenance.html?mode=preview&handoff=none' +
        (next ? `&next=${encodeURIComponent(next)}` : ''));
    }
    return new Response(null, { status: 302, headers });
  }

  // Report-only CSP violations (vercel.json's report-uri): a pageview with ads can
  // send several, so only a sample reaches Railway; the rest end here.
  if (url.pathname === '/api/csp-report' && Math.random() >= CSP_REPORT_SAMPLE) {
    return new Response(null, { status: 204 });
  }

  // Feedback stays open during maintenance (the page has its own form);
  // it's Turnstile-verified and rate-limited server-side. Previews keep it
  // gated (their page hides the form).
  const isFeedback = url.pathname === '/api/feedback' && !isPreview;

  const gated = maintenance.on || isPreview;

  // ?mode=preview tells the page to show the dev-preview copy and handoff;
  // it can't tell a preview from production's own *.vercel.app hosts.
  // ?next= carries the gated page through the handoff (not for /api/
  // fetches, which would land the tab on JSON).
  if (gated && !isFeedback && !(await validBypass(request))) {
    const gatePage = !isPreview ? '/maintenance.html'
      : url.pathname.startsWith('/api/') ? '/maintenance.html?mode=preview'
      : `/maintenance.html?mode=preview&next=${encodeURIComponent(url.pathname + url.search)}`;
    return new Response(null, {
      status: 307,
      headers: { Location: new URL(gatePage, request.url).toString() },
    });
  }

  if (url.pathname.startsWith('/api/')) {
    return proxyToBackend(request, url);
  }

  if (
    process.env.PRERENDER_ENABLED === 'true' &&
    isCrawler(request.headers.get('user-agent') || '') &&
    (DETAIL_RE.test(url.pathname) || url.pathname in STATIC_RENDER)
  ) {
    const snapshot = await fetchSnapshot(url.pathname, request.headers.get('x-real-ip'));
    if (snapshot) {
      return new Response(snapshot.body, {
        status: snapshot.status,
        headers: {
          'content-type': 'text/html; charset=utf-8',
          'cache-control': snapshot.headers.get('cache-control') ||
            'public, max-age=3600, s-maxage=86400',
          'x-prerendered': '1',
        },
      });
    }
    // snapshot undefined → fall through to SPA below
  }

  // Fall through to vercel.json rewrites (SPA fallback).
  return undefined;
}
