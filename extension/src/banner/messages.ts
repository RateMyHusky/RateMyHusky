/** The contract between the content script on Banner and the service worker.
 *
 *  Both sides import these types, so changing the shape is a compile error on
 *  the other side. There's no shared scope between a content script and a
 *  worker to catch a mismatch at runtime — a renamed field just arrives as
 *  undefined and the badge quietly renders blank. */

/** Banner term code, e.g. "202730" for Spring 2027. */
export type Term = string;

/** The one origin this feature ever touches. Opt-in, so it lives in
 *  optional_host_permissions rather than host_permissions. */
export const BANNER_ORIGIN = 'https://nubanner.neu.edu/*';

/** Narrower than the origin: Browse Classes and the rest of the registration
 *  app, not every page on the host. */
export const BANNER_MATCHES = ['https://nubanner.neu.edu/StudentRegistrationSsb/*'];

/** What RateMyHusky knows about the section behind one CRN. */
export type Section = {
  /** The section's primary instructor, exactly as Banner's Instructor column
   *  prints it — "Last, First", HTML entities decoded. The content script
   *  compares this with the live page to catch a section reassigned since the
   *  last scrape, and banner_section_instructors stores the name still
   *  escaped ("O&#39;Connell"), so the endpoint has to unescape it or every
   *  apostrophe surname reads as stale. Null when no instructor is on record. */
  instructor: string | null;
  /** Null wherever the matcher abstained, and the badge then offers a link to
   *  rate them instead of a rating. Guessing here would publish one professor's rating under
   *  another's name, which is the one failure in this feature we can't take
   *  back. */
  slug: string | null;
  rating: number | null;
  numRatings: number;
};

/** The most CRNs one request carries: Banner's largest page size (it offers
 *  10, 15, 20 or 50 per page). The endpoint's own cap has to be at least this,
 *  or the biggest page of results fails as a whole. */
export const MAX_CRNS = 50;

export type LookupRequest = {
  type: 'banner:lookup';
  term: Term;
  /** Every CRN on the page, in one request — at most MAX_CRNS. The API allows
   *  20/sec per IP and a results page lists far more sections than that. */
  crns: string[];
};

export type LookupResponse =
  | { ok: true; sections: Record<string, Section> }
  | {
      ok: false;
      message: string;
      /** Worth asking again later: a 429, a 5xx, a timeout or a dropped
       *  connection. During registration a whole campus shares a few egress
       *  IPs, so a 429 is the expected failure, not a permanent one. */
      retry: boolean;
      /** The student switched "Show ratings on Banner" off while this tab
       *  was open. The content script stops and takes its badges down. */
      disabled?: true;
    };

/** False once the extension has been updated or reloaded under this page:
 *  the content script is orphaned, and every chrome.runtime call throws
 *  "Extension context invalidated" synchronously. */
export function extensionAlive(): boolean {
  try {
    return !!chrome.runtime?.id;
  } catch {
    return false;
  }
}

/** Content-script side of the call.
 *
 *  The worker does the fetching because a request made from the Banner page
 *  carries `Origin: https://nubanner.neu.edu`, and check_origin in
 *  backend/server.py 403s anything outside ALLOWED_ORIGINS. The worker's
 *  chrome-extension:// origin is the one that goes in EXTENSION_ORIGINS. */
export async function lookup(term: Term, crns: string[]): Promise<LookupResponse> {
  if (crns.length === 0) return { ok: true, sections: {} };

  const request: LookupRequest = { type: 'banner:lookup', term, crns };
  try {
    const response = (await chrome.runtime.sendMessage(request)) as LookupResponse | undefined;
    // No listener answered: the worker was mid-restart. Try again later.
    return response ?? { ok: false, message: 'No response', retry: true };
  } catch (err) {
    // The worker was asleep or reloading (worth another try), or the
    // extension updated under this page (not: nothing here works any more).
    return { ok: false, message: (err as Error).message, retry: extensionAlive() };
  }
}

/** Where the worker leaves the professor a badge click asked for, for the
 *  popup to pick up as it opens. Session storage: it's gone when the browser
 *  closes, and a stale one never opens a professor days later. */
export const OPEN_KEY = 'rmh:open-professor';

export type OpenRequest = { type: 'banner:open'; slug: string };

/** Content-script side of a badge click: the worker opens the popup on that
 *  professor, or the site in a new tab if Chrome won't.
 *
 *  Returns whether it took the click. When it can't — the extension updated
 *  under this page, so sendMessage throws synchronously, before any promise
 *  exists to .catch — the badge leaves the click alone and its href opens the
 *  professor's page instead of nothing happening at all. */
export function openProfessor(slug: string): boolean {
  if (!extensionAlive()) return false;
  const request: OpenRequest = { type: 'banner:open', slug };
  try {
    chrome.runtime.sendMessage(request).catch(() => {
      // The worker is reloading. The click does nothing this once.
    });
    return true;
  } catch {
    return false;
  }
}
