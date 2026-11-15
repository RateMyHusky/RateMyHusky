import { useEffect, useRef, useState } from 'react';
import { errorMessage, searchProfessors, type ProfessorSuggestion } from '../api';
import { ChevronIcon, ClockIcon, CloseIcon, SearchIcon } from '../components/icons';
import SavedList from '../components/SavedList';
import { score } from '../utils/format';
import './Search.css';

type Recent = { name: string; dept: string | null; slug: string };

const RECENTS_KEY = 'rmh-extension-recent-searches';
const MAX_RECENTS = 6;
/** Long enough that typing a name sends one request, not one per letter. */
const DEBOUNCE_MS = 150;

function loadRecents(): Recent[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(RECENTS_KEY) ?? '[]');
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (r): r is Recent =>
          !!r &&
          typeof r.name === 'string' &&
          typeof r.slug === 'string' &&
          (typeof r.dept === 'string' || r.dept === null),
      )
      .slice(0, MAX_RECENTS);
  } catch {
    // Storage off or malformed: the popup still works, just without recents.
    return [];
  }
}

function saveRecents(recents: Recent[]): void {
  try {
    localStorage.setItem(RECENTS_KEY, JSON.stringify(recents));
  } catch {
    // Same as above: the visible list is still right for this popup.
  }
}

type Results =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; query: string; matches: ProfessorSuggestion[] }
  | { status: 'error'; message: string };

/** The popup's home screen, and the picker Compare uses to add a professor.
 *  Both end in onPick: the caller decides whether that opens an Overview or
 *  joins a comparison, so search itself never navigates. */
export default function Search({
  onPick,
  heading,
  exclude = [],
  showSaved = false,
}: {
  onPick: (slug: string) => void;
  /** Shown above the box in picker mode, e.g. "Compare with…". */
  heading?: string;
  /** Professors already in the comparison, left out of the results. */
  exclude?: string[];
  showSaved?: boolean;
}) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Results>({ status: 'idle' });
  const [recents, setRecents] = useState<Recent[]>(loadRecents);
  const input = useRef<HTMLInputElement>(null);

  const q = query.trim();

  useEffect(() => {
    if (q.length < 2) {
      setResults({ status: 'idle' });
      return;
    }
    setResults({ status: 'loading' });
    // A stale response can land after a newer one; the flag drops it.
    let current = true;
    const timer = window.setTimeout(() => {
      searchProfessors(q, 8).then(
        (matches) => current && setResults({ status: 'ready', query: q, matches }),
        (err) => current && setResults({ status: 'error', message: errorMessage(err) }),
      );
    }, DEBOUNCE_MS);
    return () => {
      current = false;
      window.clearTimeout(timer);
    };
  }, [q]);

  function pick(p: Recent): void {
    const next = [p, ...recents.filter((r) => r.slug !== p.slug)].slice(0, MAX_RECENTS);
    setRecents(next);
    saveRecents(next);
    onPick(p.slug);
  }

  function clearRecents(): void {
    setRecents([]);
    saveRecents([]);
  }

  const matches =
    results.status === 'ready' ? results.matches.filter((m) => !exclude.includes(m.slug)) : [];
  const shownRecents = recents.filter((r) => !exclude.includes(r.slug));

  return (
    <div className="search">
      {heading && <p className="section-label">{heading}</p>}

      <form
        className="search-box"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          // Enter takes the top result, but only once it's for what's typed.
          if (results.status === 'ready' && results.query === q && matches[0]) pick(matches[0]);
        }}
      >
        <SearchIcon className="search-icon" />
        <input
          ref={input}
          autoFocus
          aria-label="Search professors"
          placeholder="Search professors…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {query && (
          <button
            className="search-clear"
            type="button"
            aria-label="Clear search"
            onClick={() => {
              setQuery('');
              input.current?.focus();
            }}
          >
            <CloseIcon />
          </button>
        )}
      </form>

      {q.length === 0 ? (
        <>
          {showSaved && <SavedList onOpen={onPick} />}

          <section className="search-section" aria-label="Recent searches">
            <div className="search-head">
              <p className="section-label">Recent Searches</p>
              {shownRecents.length > 0 && (
                <button className="link-btn" type="button" onClick={clearRecents}>
                  Clear
                </button>
              )}
            </div>
            {shownRecents.length > 0 ? (
              <ul className="row-list">
                {shownRecents.map((r) => (
                  <li key={r.slug}>
                    <button className="row" type="button" onClick={() => pick(r)}>
                      <ClockIcon className="row-icon" />
                      <span className="row-main">
                        <span className="row-title">{r.name}</span>
                        {r.dept && <span className="row-meta">{r.dept}</span>}
                      </span>
                      <ChevronIcon className="row-chev" />
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted search-empty">Professors you open will show up here.</p>
            )}
          </section>
        </>
      ) : (
        <section className="search-section" aria-label="Search results" aria-live="polite">
          {q.length < 2 ? (
            <p className="muted search-empty">Keep typing — at least 2 letters.</p>
          ) : results.status === 'error' ? (
            <p className="muted search-empty">{results.message}</p>
          ) : results.status !== 'ready' || results.query !== q ? (
            <p className="muted search-empty">Searching…</p>
          ) : matches.length === 0 ? (
            <p className="muted search-empty">No professors match “{q}”.</p>
          ) : (
            <ul className="row-list">
              {matches.map((m) => (
                <li key={m.slug}>
                  <button
                    className="row"
                    type="button"
                    onClick={() => pick({ name: m.name, dept: m.dept, slug: m.slug })}
                  >
                    <span className="row-main">
                      <span className="row-title">{m.name}</span>
                      {m.dept && <span className="row-meta">{m.dept}</span>}
                    </span>
                    {m.rating != null && (
                      <span className="row-score">
                        <span className="row-star" aria-hidden="true">
                          ★
                        </span>
                        {score(m.rating)}
                      </span>
                    )}
                    <ChevronIcon className="row-chev" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
