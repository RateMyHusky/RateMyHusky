import type { ProfileStatus } from '../api/api';

/* One status per auth token, so every popup and page view reuses a single GET /api/profile. */
const cache = new Map<string, Promise<ProfileStatus | null>>();

/* api.ts reads import.meta.env at load, so it is imported lazily to keep this module runnable under tsx. */
const defaultFetcher = () => import('../api/api').then((m) => m.fetchProfileStatus());

export function getProfileStatus(fetcher: () => Promise<ProfileStatus> = defaultFetcher): Promise<ProfileStatus | null> {
  const token = localStorage.getItem('auth_token');
  if (!token) return Promise.resolve(null);
  const hit = cache.get(token);
  if (hit) return hit;
  const pending: Promise<ProfileStatus | null> = fetcher().catch(() => {
    if (cache.get(token) === pending) cache.delete(token);
    return null;
  });
  cache.set(token, pending);
  return pending;
}

const listeners = new Set<() => void>();

/* Called after the cache changes, so mounted hooks re-read it. */
export function onProfileSaved(fn: () => void): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

export function markProfileSaved(): void {
  const token = localStorage.getItem('auth_token');
  if (token) cache.set(token, Promise.resolve({ exists: true, optedOut: false }));
  listeners.forEach((fn) => fn());
}
