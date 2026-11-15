import type { SavedEntry } from './messages';

export const SAVED_KEY = 'rmh:saved-professor-courses:v1';
const MAX_SAVED = 100;
/** What a site slug looks like. Anything from the page is checked against it
 *  before it's stored or put in a URL. */
export const SLUG = /^[a-z0-9][a-z0-9-]{0,119}$/;
const valid = (item: unknown): item is SavedEntry => {
  if (!item || typeof item !== 'object') return false;
  const s = item as Partial<SavedEntry>;
  return typeof s.slug === 'string' && SLUG.test(s.slug) &&
    typeof s.name === 'string' && s.name.trim().length > 0 && s.name.length <= 160 &&
    typeof s.course === 'string' && s.course.trim().length > 0 && s.course.length <= 180 &&
    typeof s.term === 'string' && /^\d{6}$/.test(s.term) &&
    typeof s.crn === 'string' && /^\d{1,10}$/.test(s.crn) &&
    typeof s.savedAt === 'number' && Number.isFinite(s.savedAt);
};

export async function readSaved(): Promise<SavedEntry[]> {
  const data = await chrome.storage.local.get(SAVED_KEY);
  const entries: unknown = data[SAVED_KEY];
  return Array.isArray(entries) ? entries.filter(valid).slice(0, MAX_SAVED) : [];
}

/** One entry per professor + course + term, even if several CRNs list it. */
export function entryId(s: Pick<SavedEntry, 'slug' | 'course' | 'term'>): string {
  return JSON.stringify([s.slug, s.course, s.term]);
}

export async function saveProfessorCourse(entry: SavedEntry): Promise<void> {
  if (!valid(entry)) throw new Error('Invalid saved professor');
  const current = await readSaved();
  const previous = current.find((s) => entryId(s) === entryId(entry));
  const next = current.filter((s) => entryId(s) !== entryId(entry));
  next.unshift({ ...entry, savedAt: previous?.savedAt ?? entry.savedAt });
  await chrome.storage.local.set({ [SAVED_KEY]: next.slice(0, MAX_SAVED) });
}

export async function removeSaved(entry: Pick<SavedEntry, 'slug' | 'course' | 'term'>): Promise<void> {
  const current = await readSaved();
  await chrome.storage.local.set({
    [SAVED_KEY]: current.filter((item) => entryId(item) !== entryId(entry)),
  });
}
