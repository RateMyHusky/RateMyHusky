// Decode HTML entities (&amp; &#39; &quot; …) so the evidence-table snippet (entities NOT
// unescaped) and the professor page body (already html.unescape'd) converge. Browser-safe:
// uses DOMParser when available, falls back to a small map (also lets the tsx self-check run
// under Node, where DOMParser is absent). Runs unconditionally (not gated on '&' presence) so
// body and snippet always take the same normalization path, even when only one side has tag-like
// text that DOMParser would otherwise strip differently.
function decodeEntities(s: string): string {
  if (typeof DOMParser !== 'undefined') {
    return new DOMParser().parseFromString(s, 'text/html').documentElement.textContent ?? s;
  }
  return s
    .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"').replace(/&#0*39;/g, "'").replace(/&#x27;/gi, "'")
    .replace(/&apos;/g, "'").replace(/&nbsp;/g, ' ');
}

// Match Ask citation snippets against professor-page bodies. Both sides are HTML-entity-decoded
// and NFKC-normalized so the evidence-table snippet and the html.unescape'd page body converge,
// then lowercased + whitespace-collapsed + trimmed (mirrors Professor.tsx deduplicateByText).
function normalize(s: string): string {
  return decodeEntities(s).normalize('NFKC').toLowerCase().replace(/\s+/g, ' ').trim();
}

export function matchesPin(body: string, snippet: string): boolean {
  const b = normalize(body);
  const s = normalize(snippet);
  if (!b || !s) return false;
  // snippet is a prefix of the body (Ask sends body[:200]); tolerate the body being shorter
  // than 200 chars (then snippet is a prefix of nothing longer, so require the body to cover
  // at least 80% of the snippet — kills tiny-prefix false matches like a short review whose
  // full text happens to be a prefix of some other, longer cited review's snippet).
  return b.startsWith(s) || (s.startsWith(b) && b.length >= 0.8 * s.length);
}

export function isPinned(body: string, snippets: string[]): boolean {
  return snippets.some((s) => matchesPin(body, s));
}

export function pinnedFirst<T>(items: T[], getBody: (t: T) => string, snippets: string[]): T[] {
  if (snippets.length === 0) return items;
  const pinned: T[] = [];
  const rest: T[] = [];
  for (const it of items) {
    if (isPinned(getBody(it), snippets)) pinned.push(it);
    else rest.push(it);
  }
  return [...pinned, ...rest];
}

// Identifies one citation click: the answer it came from (askedAt) plus the cited source.
// Two citations from the same answer get different keys, so each click re-applies the pins.
// Never '' — the professor page's "nothing applied yet" sentinel.
export function pinClickKey(pins: { askedAt: number; clicked: { source: string | null; snippet: string } }): string {
  return JSON.stringify([pins.askedAt, pins.clicked.source, pins.clicked.snippet]);
}
