import { useEffect, useRef, useState } from 'react';
import {
  isUnavailable,
  fetchProfessorProfile,
  searchProfessors,
  type ProfessorProfile,
  type ProfessorReview,
  type ProfessorSuggestion,
} from './api';

type RecentSearch = { name: string; dept: string | null; slug: string };

const RECENTS_KEY = 'rmh-extension-recent-searches';

function loadRecents(): RecentSearch[] {
  try {
    const saved = localStorage.getItem(RECENTS_KEY);
    if (!saved) return [];
    const parsed: unknown = JSON.parse(saved);
    if (
      Array.isArray(parsed) &&
      parsed.every(
        (item) =>
          item &&
          typeof item.name === 'string' &&
          (typeof item.dept === 'string' || item.dept === null) &&
          typeof item.slug === 'string',
      )
    ) {
      return parsed.slice(0, 6) as RecentSearch[];
    }
  } catch {
    // A fresh popup should still work if storage is unavailable or malformed.
  }
  return [];
}

function SearchIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="10.8" cy="10.8" r="6.6" />
      <path d="m16 16 4.2 4.2" />
    </svg>
  );
}

function ClockIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7v5l3.2 2" />
    </svg>
  );
}

function ChevronIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="m9 5 7 7-7 7" />
    </svg>
  );
}

function displayDepartment(dept: string | null): string {
  if (!dept) return 'Professor';
  const abbreviations: Record<string, string> = {
    'Computer Science': 'CS',
    'Electrical and Computer Engineering': 'ECE',
    'Mechanical and Industrial Engineering': 'ME',
  };
  return abbreviations[dept] ?? dept;
}

function formatReviewDate(value: string): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric' }).format(date);
}

function ReviewCard({ review }: { review: ProfessorReview }) {
  const tags = review.tags.split('--').map((tag) => tag.trim()).filter(Boolean);
  return (
    <article className="review-card">
      <div className="review-card-top">
        <div className="stars" aria-label={`${review.quality} out of 5 stars`}>
          {Array.from({ length: 5 }, (_, index) => (
            <span className={index < Math.round(review.quality) ? 'filled' : ''} key={index}>★</span>
          ))}
        </div>
        <span className="review-date">{formatReviewDate(review.date)}</span>
      </div>
      {review.comment ? <p className="review-comment">{review.comment}</p> : (
        <p className="review-comment muted">No written comment for this rating.</p>
      )}
      <div className="review-details">
        {review.courseCode && <span>{review.courseCode}</span>}
        <span>Difficulty {review.difficulty}/5</span>
      </div>
      {tags.length > 0 && (
        <div className="review-tags">
          {tags.map((tag) => <span className="review-tag" key={tag}>{tag}</span>)}
        </div>
      )}
    </article>
  );
}

function ProfileAvatar({ imageUrl }: { imageUrl: string | null | undefined }) {
  const [failed, setFailed] = useState(false);

  useEffect(() => setFailed(false), [imageUrl]);

  return imageUrl && !failed ? (
    <img src={imageUrl} alt="" onError={() => setFailed(true)} />
  ) : (
    <span className="avatar large" aria-hidden="true" />
  );
}

function ProfileView({ profile }: { profile: ProfessorProfile }) {
  const [reviewSort, setReviewSort] = useState<'newest' | 'highest' | 'lowest'>('newest');
  const reviews = profile.sources.rmp.reviews;
  const orderedReviews = [...reviews].sort((a, b) => {
    if (reviewSort === 'highest') return b.quality - a.quality;
    if (reviewSort === 'lowest') return a.quality - b.quality;
    return (Date.parse(b.date) || 0) - (Date.parse(a.date) || 0);
  });

  // Build keys from review content because the current API type has no review ID
  // Include occurrence count so identical reviews still have distinct keys
  const occurrences = new Map<string, number>();
  const keyedReviews = orderedReviews.map((review) => {
    const keyBase = review.id != null
      ? String(review.id)
      : JSON.stringify([review.date, review.courseCode, review.course, review.quality,
        review.difficulty, review.comment, review.tags]);
    const occurrence = occurrences.get(keyBase) ?? 0;
    occurrences.set(keyBase, occurrence + 1);
    return { review, key: `${keyBase}-${occurrence}` };
  });

  return (
    <section className="profile-content">
      <div className="content-heading">
        <div>
          <h1>Student Reviews <span className="count">({reviews.length})</span></h1>
          <p>Ratings and feedback from Rate My Professors</p>
        </div>
        <label className="sort-control">
          <span className="visually-hidden">Sort reviews</span>
          <select value={reviewSort} onChange={(event) => setReviewSort(event.target.value as typeof reviewSort)}>
            <option value="newest">Newest</option>
            <option value="highest">Highest rated</option>
            <option value="lowest">Lowest rated</option>
          </select>
        </label>
      </div>
      {keyedReviews.length > 0 ? (
        <div className="review-list">
          {keyedReviews.map(({ review, key }) => <ReviewCard key={key} review={review} />)}
        </div>
      ) : (
        <p className="profile-empty">No reviews are available for this professor yet.</p>
      )}
    </section>
  );
}

export default function App() {
  const [query, setQuery] = useState('');
  const [recents, setRecents] = useState<RecentSearch[]>(loadRecents);
  const [results, setResults] = useState<ProfessorSuggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selectedProfessor, setSelectedProfessor] = useState<ProfessorSuggestion | null>(null);
  const [profile, setProfile] = useState<ProfessorProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileError, setProfileError] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const profileRequestId = useRef(0);
  const latestQuery = useRef('');
  const [resultsQuery, setResultsQuery] = useState('');

  useEffect(() => {
    const normalized = query.trim();
    setResults([]);
    setResultsQuery('');
    if (normalized.length < 2) {
      setResults([]);
      setLoading(false);
      setError('');
      return;
    }

    let active = true;
    setLoading(true);
    setError('');
    const timeout = window.setTimeout(() => {
      searchProfessors(normalized, 8)
        .then((matches) => {
          if (active && latestQuery.current === normalized) {
            setResults(matches);
            setResultsQuery(normalized);
          }
        })
        .catch((err: unknown) => {
          if (!active) return;
          setResults([]);
          setError(
            isUnavailable(err)
              ? 'Search is temporarily unavailable. Try again in a moment.'
              : 'Could not load search results. Please try again.',
          );
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    }, 120);

    return () => {
      active = false;
      window.clearTimeout(timeout);
    };
  }, [query]);

  function remember(professor: RecentSearch) {
    const updated = [
      professor,
      ...recents.filter((item) => item.slug !== professor.slug),
    ].slice(0, 6);
    setRecents(updated);
    try {
      localStorage.setItem(RECENTS_KEY, JSON.stringify(updated));
    } catch {
      // Search still works when browser storage is disabled.
    }
  }

  function openProfessor(professor: ProfessorSuggestion) {
    remember({
      name: professor.name,
      dept: professor.dept,
      slug: professor.slug,
    });
    setSelectedProfessor(professor);
    setProfile(null);
    setProfileError('');
    setProfileLoading(true);
    const requestId = ++profileRequestId.current;
    fetchProfessorProfile(professor.slug)
      .then((nextProfile) => {
        if (requestId === profileRequestId.current) setProfile(nextProfile);
      })
      .catch((err: unknown) => {
        if (requestId !== profileRequestId.current) return;
        setProfileError(
          isUnavailable(err)
            ? 'Professor details are temporarily unavailable. Check your connection and try again.'
            : 'Could not load professor details. Please try again.',
        );
      })
      .finally(() => {
        if (requestId === profileRequestId.current) setProfileLoading(false);
      });
  }

  function clearRecents() {
    setRecents([]);
    try {
      localStorage.setItem(RECENTS_KEY, '[]');
    } catch {
      // Clearing the visible list still works without browser storage.
    }
  }

  const trimmedQuery = query.trim();
  const showRecents = trimmedQuery.length === 0;

  return (
    <div className="popup">
      <header className="bar">
        <img className="brand-icon" src="/neu-husky-icon.png" alt="" />
        <span className="wordmark">RateMyHusky</span>
      </header>

      {selectedProfessor ? (
        <>
          <div className="profile-titlebar">
            <button className="back-button" type="button" aria-label="Back to search" onClick={() => {
              profileRequestId.current += 1;
              setSelectedProfessor(null);
              setProfile(null);
              setProfileLoading(false);
              setProfileError('');
            }}><ChevronIcon /></button>
            <div className="profile-identity">
              <ProfileAvatar imageUrl={profile?.identity.imageUrl} />
              <div>
                <h1>{profile?.identity.name ?? selectedProfessor.name}</h1>
                <p>{profile?.identity.department ?? displayDepartment(selectedProfessor.dept)}</p>
                {profile?.summary.rating != null && (
                  <span className="identity-rating"><b>★ {profile.summary.rating.toFixed(1)}</b> / 5 · {profile.summary.numRatings.toLocaleString()} ratings</span>
                )}
              </div>
            </div>
          </div>
          {profileLoading ? <p className="profile-empty">Loading professor details…</p> : profileError ? (
            <p className="profile-empty error-state">{profileError}</p>
          ) : profile ? <ProfileView profile={profile} /> : null}
        </>
      ) : <main className="body">
        <form
          className="search-box"
          role="search"
          onSubmit={(event) => {
            event.preventDefault();
            if (!loading && !error && resultsQuery === latestQuery.current && results[0]) {
              openProfessor(results[0]);
            }
          }}
        >
          <SearchIcon />
          <input
            ref={inputRef}
            autoFocus
            aria-label="Search professors"
            placeholder="Search professors..."
            value={query}
            onChange={(event) => {
              latestQuery.current = event.target.value.trim();
              setResults([]);
              setResultsQuery('');
              setLoading(latestQuery.current.length >= 2);
              setQuery(event.target.value);
            }}
          />
          {query && (
            <button
              className="icon-button clear-query"
              type="button"
              aria-label="Clear search"
              onClick={() => {
                latestQuery.current = '';
                setResults([]);
                setResultsQuery('');
                setQuery('');
                inputRef.current?.focus();
              }}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="m6 6 12 12M18 6 6 18" />
              </svg>
            </button>
          )}
        </form>

        {showRecents ? (
          <section className="recent-section" aria-label="Recent searches">
            <div className="section-heading">
              <h1>Recent Searches</h1>
              {recents.length > 0 && (
                <button className="text-button" type="button" onClick={clearRecents}>
                  Clear
                </button>
              )}
            </div>
            {recents.length > 0 ? (
              <ul className="recent-list">
                {recents.map((recent) => (
                  <li key={recent.slug}>
                    <button
                      className="recent-row"
                      type="button"
                      onClick={() => openProfessor({
                        type: 'professor', name: recent.name, dept: recent.dept,
                        slug: recent.slug, rating: null,
                      })}
                    >
                      <ClockIcon />
                      <span className="recent-name">{recent.name}</span>
                      <span className="recent-dept">{recent.dept}</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="empty-state">Your recent searches will show up here.</p>
            )}
          </section>
        ) : (
          <section className="results-section" aria-label="Search results" aria-live="polite">
            {loading ? (
              <p className="empty-state">Searching…</p>
            ) : error ? (
              <p className="empty-state error-state">{error}</p>
            ) : trimmedQuery.length < 2 ? (
              <p className="empty-state">Type at least 2 characters to search.</p>
            ) : resultsQuery === trimmedQuery && results.length > 0 ? (
              <ul className="results-list">
                {results.map((professor) => (
                  <li key={professor.slug}>
                    <button
                      className="result-row"
                      type="button"
                      onClick={() => openProfessor(professor)}
                    >
                      <span className="avatar" aria-hidden="true" />
                      <span className="result-copy">
                        <span className="result-name">{professor.name}</span>
                        <span className="result-dept">{displayDepartment(professor.dept)}</span>
                      </span>
                      <ChevronIcon />
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="empty-state">No professors found for “{trimmedQuery}”.</p>
            )}
          </section>
        )}
      </main>}
    </div>
  );
}
