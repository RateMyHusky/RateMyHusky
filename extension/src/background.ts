
type Section = {
  instructor: string | null;
  slug: string | null;
  rating: number | null;
  numRatings: number;
};

type LookupRequest = {
  type: 'banner:lookup';
  term: string;
  crns: string[];
};

type LookupResponse =
  | { ok: true; sections: Record<string, Section> }
  | { ok: false; message: string };

const API_URL = 'https://ratemyhusky.com/api/banner/sections';
const MAX_CRNS = 50;

// request ratings from the existing RateMyHusky database
async function lookupSections(
  request: LookupRequest
): Promise<LookupResponse> {
  const { term, crns } = request;

  if (!/^\d{6}$/.test(term)) {
    return { ok: false, message: 'Invalid term' };
  }

  if (
    !Array.isArray(crns) ||
    crns.length === 0 ||
    crns.length > MAX_CRNS ||
    crns.some(crn => typeof crn !== 'string' || !/^\d{1,10}$/.test(crn))
  ) {
    return { ok: false, message: 'Invalid CRNs' };
  }

  const uniqueCrns = [...new Set(crns)];

  const params = new URLSearchParams({
    term,
    crns: uniqueCrns.join(','),
  });

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);

  try {
    const response = await fetch(`${API_URL}?${params}`, {
      method: 'GET',
      credentials: 'omit',
      signal: controller.signal,
    });

    if (!response.ok) {
      return {
        ok: false,
        message: `Rating lookup failed: ${response.status}`,
      };
    }

    const sections = (await response.json()) as Record<string, Section>;

    return { ok: true, sections };
  } catch (error) {
    return {
      ok: false,
      message: error instanceof Error ? error.message : 'Lookup failed',
    };
  } finally {
    clearTimeout(timeout);
  }
}

// receive requests from the extension's content script
chrome.runtime.onMessage.addListener(
  (message: LookupRequest, sender, sendResponse) => {
    if (message?.type !== 'banner:lookup') return false;

    if (sender.id !== chrome.runtime.id) {
      sendResponse({ ok: false, message: 'Unauthorized sender' });
      return false;
    }

    void lookupSections(message).then(sendResponse);
    return true;
  }
);
