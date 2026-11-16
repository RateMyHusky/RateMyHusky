# Putting Cloudflare in front of Vercel

Why: Vercel's Hobby plan caps CDN requests (1M/month) and Fluid CPU (4 h/month). Cloudflare
answers photos and `/assets/*` itself and can block bots at the edge, so those requests
never reach Vercel. Vercel still builds and hosts the site; `middleware.ts`, deploys and PRs
do not change.

Prerequisites: a Cloudflare account, the **Name.com** login (the registrar) and Vercel team
access (to read the DNS records). The domain currently uses `ns1/ns2.vercel-dns.com`, so
Vercel holds every DNS record.

## 0. Code (this PR)
`middleware.ts` now trusts `CF-Connecting-IP` only when the request also carries
`x-rmh-cf-secret` equal to the `CF_SHARED_SECRET` env var (`clientIp.ts`). Without the
secret it behaves exactly as before. Deploy this **before** the cutover, with
`CF_SHARED_SECRET` set in Vercel (Production + Preview) to a long random value, e.g.
`openssl rand -hex 32`.

## 1. Add the site to Cloudflare
1. Cloudflare dashboard → Add a domain → `ratemyhusky.com` → Free plan.
2. Cloudflare imports whatever DNS it can find. **Compare against Vercel → project → Domains
   / DNS** and recreate every record, especially any MX, TXT (SPF/DKIM/DMARC, Google site
   verification) and CNAME records. A missing record breaks email or a verification.
3. Set the apex and `www` records to the values Vercel shows (currently A `64.29.17.1` and
   `www` → `216.198.79.65`; re-check, they can change). Leave them **Proxied** (orange cloud).

## 2. Settings before the cutover
- SSL/TLS → **Full (strict)**. Never Flexible: it causes redirect loops with Vercel.
- Speed → turn **off** Rocket Loader and Auto Minify (they rewrite the inline GA script and
  break the CSP script hashes in `vercel.json`).
- Caching → keep "Respect origin" TTL. By default Cloudflare caches only static file
  extensions (images, js, css) and **not** HTML or JSON, so `/api/*`, the maintenance gate
  and the crawler snapshots stay uncached.
- Rules → Transform Rules → Modify Request Header, for all incoming requests:
  set `x-rmh-cf-secret` = the same `CF_SHARED_SECRET` value.
- Rules → Cache Rules: `/photos/*` and `/assets/*` → Eligible for cache, Edge TTL 1 month.

## 3. Bot rules (free-plan limits change: check the dashboard)
- Security → Bots → turn on **Bot Fight Mode** and **Block AI bots** if offered. Verified
  crawlers such as Googlebot are not affected by Bot Fight Mode.
- Security → WAF → Rate limiting → one rule: `/api/*`, per IP, over ~100 requests / 10 s →
  block for 1 min.
- Optionally challenge AWS traffic that claims to be Chrome (ASN rule) after checking the
  Security → Events log, so real students on campus networks are not caught.

## 4. Cutover
At **Name.com** → Nameservers → replace `ns1/ns2.vercel-dns.com` with the two Cloudflare
gave you. Propagation is usually minutes to a few hours. Do it at a quiet hour.

## 5. Verify
- `dig +short NS ratemyhusky.com` shows Cloudflare.
- `curl -sI https://ratemyhusky.com/photos/<any>.webp | grep -i cf-cache-status` →
  `HIT` on the second request.
- Site, sign-in (Google OAuth), `/api/stats`, a professor page, a crawler snapshot
  (`curl -A Googlebot https://ratemyhusky.com/professors/<slug>` has `x-prerendered: 1`).
- Backend logs: `x-rmh-client-ip` should be a student address, not a Cloudflare one.
- A day later: Vercel → Usage, requests/day should be well below the earlier baseline.

## Rollback
Put the Vercel nameservers back at Name.com. Remove nothing in Vercel; it kept serving.

## Caveats
- Vercel's own Firewall and Observability see Cloudflare's addresses, not students'.
- Vercel documents proxying as supported but not recommended; keep SSL on Full (strict).
- Cloudflare's free plan can suspend a site over limits; check its terms and limits page.
