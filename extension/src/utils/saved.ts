/** Professors a student saved from the popup, kept in this browser only and
 *  never sent anywhere. Just the professor: nothing read from Banner — no
 *  course, term or CRN — is stored, so there's no record of what anyone was
 *  registering for. */

export type SavedProfessor = { slug: string; name: string; savedAt: number };

export const SAVED_KEY = 'rmh:saved-professors:v2';
/** The first version also kept the Banner course, term and CRN. Read once
 *  for the professors in it, then deleted so those details don't linger. */
const LEGACY_KEY = 'rmh:saved-professor-courses:v1';
const MAX_SAVED = 100;

/** What a site slug looks like. Anything stored or put in a URL is checked
 *  against it first. */
export const SLUG = /^[a-z0-9][a-z0-9-]{0,119}$/;

export function isSaved(item: unknown): item is SavedProfessor {
  if (!item || typeof item !== 'object') return false;
  const s = item as Partial<SavedProfessor>;
  return (
    typeof s.slug === 'string' &&
    SLUG.test(s.slug) &&
    typeof s.name === 'string' &&
    s.name.trim().length > 0 &&
    s.name.length <= 160 &&
    typeof s.savedAt === 'number' &&
    Number.isFinite(s.savedAt)
  );
}

/** Newest first, one entry per professor. */
export function normalize(items: unknown[]): SavedProfessor[] {
  const seen = new Set<string>();
  const out: SavedProfessor[] = [];
  for (const item of items) {
    if (!item || typeof item !== 'object') continue;
    const { slug, name, savedAt } = item as Partial<SavedProfessor>;
    const entry = { slug, name, savedAt };
    if (!isSaved(entry) || seen.has(entry.slug)) continue;
    seen.add(entry.slug);
    out.push(entry);
  }
  return out.slice(0, MAX_SAVED);
}

export async function readSaved(): Promise<SavedProfessor[]> {
  const data = await chrome.storage.local.get([SAVED_KEY, LEGACY_KEY]);
  const current: unknown = data[SAVED_KEY];
  const legacy: unknown = data[LEGACY_KEY];
  if (legacy === undefined) return Array.isArray(current) ? normalize(current) : [];

  const merged = normalize([
    ...(Array.isArray(current) ? current : []),
    ...(Array.isArray(legacy) ? legacy : []),
  ]);
  await chrome.storage.local.set({ [SAVED_KEY]: merged });
  await chrome.storage.local.remove(LEGACY_KEY);
  return merged;
}

export async function save(slug: string, name: string): Promise<void> {
  const current = await readSaved();
  await chrome.storage.local.set({
    [SAVED_KEY]: normalize([{ slug, name, savedAt: Date.now() }, ...current]),
  });
}

export async function unsave(slug: string): Promise<void> {
  const current = await readSaved();
  await chrome.storage.local.set({ [SAVED_KEY]: current.filter((s) => s.slug !== slug) });
}
