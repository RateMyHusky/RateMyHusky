import { useEffect, useRef, useState } from 'react';
import { errorMessage, searchProfessors, type ProfessorSuggestion } from '../api';
import { ChevronIcon, ClockIcon, CloseIcon, ScaleIcon, SearchIcon } from '../components/icons';
import Photo from '../components/Photo';
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

/** The face where there is one, initials where there isn't — two "Kim"s are
 *  told apart faster by face than by department. */
function Avatar({ match }: { match: ProfessorSuggestion }) {
  const initials = match.name
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();
  return (
    <Photo
      key={match.imageUrl ?? ''}
      url={match.imageUrl}
      className="row-avatar"
      style={{ objectPosition: `${match.focusX ?? 50}% ${match.focusY ?? 30}%` }}
      fallback={
        <span className="row-avatar initials" aria-hidden="true">
          {initials}
        </span>
      }
    />
  );
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
  onCompare,
  heading,
  exclude = [],
  showSaved = false,
}: {
  onPick: (slug: string) => void;
  /** Starts a comparison from a result row. Left off in picker mode, where
   *  picking already means comparing. */
  onCompare?: (slug: string) => void;
  /** Shown above the box in picker mode, e.g. "Compare with…". */
  heading?: string;
  /** Professors already in the comparison, left out of the results. */
  exclude?: string[];
  /** Lists saved professors above Recent Searches; picking one goes to onPick. */
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
          onKeyDown={(e) => {
            // Escape empties the box before it goes back a screen.
            if (e.key === 'Escape' && query) {
              e.preventDefault();
              setQuery('');
            }
          }}
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
          {showSaved && <SavedList onOpen={onPick} exclude={exclude} />}

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
                <li key={m.slug} className="row-wrap">
                  <button
                    className="row"
                    type="button"
                    onClick={() => pick({ name: m.name, dept: m.dept, slug: m.slug })}
                  >
                    <Avatar match={m} />
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
                  {onCompare && (
                    <button
                      className="row-remove"
                      type="button"
                      onClick={() => onCompare(m.slug)}
                      aria-label={`Compare ${m.name}`}
                      title="Compare"
                    >
                      <ScaleIcon />
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
