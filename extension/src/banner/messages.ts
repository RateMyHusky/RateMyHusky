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
  /** As Banner spells it — "Last, First". Null when no instructor is on
   *  record for the section. */
  instructor: string | null;
  /** Null wherever the matcher abstained, and the badge then shows the name
   *  with no rating. Guessing here would publish one professor's rating under
   *  another's name, which is the one failure in this feature we can't take
   *  back. */
  slug: string | null;
  rating: number | null;
  numRatings: number;
};

export type LookupRequest = {
  type: 'banner:lookup';
  term: Term;
  /** Every CRN on the page, in one request. The API allows 20/sec per IP and
   *  a results page lists far more sections than that. */
  crns: string[];
};

export type LookupResponse =
  | { ok: true; sections: Record<string, Section> }
  | { ok: false; message: string };

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
    return (await chrome.runtime.sendMessage(request)) as LookupResponse;
  } catch (err) {
    // The worker was asleep, is reloading, or the extension just updated.
    // Not worth surfacing on the page: no badges is the right failure here.
    return { ok: false, message: (err as Error).message };
  }
}
