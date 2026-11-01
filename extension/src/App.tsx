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

const DEFAULT_RECENTS: RecentSearch[] = [
  { name: 'Daniela Rus', dept: 'CS', slug: 'daniela-rus' },
  { name: 'David Kaeli', dept: 'EECS', slug: 'david-kaeli' },
  { name: 'Sarah Ostadabbas', dept: 'ECE', slug: 'sarah-ostadabbas' },
  { name: 'Kristina Lynch', dept: 'ME', slug: 'kristina-lynch' },
];

const RECENTS_KEY = 'rmh-extension-recent-searches';

function loadRecents(): RecentSearch[] {
  try {
    const saved = localStorage.getItem(RECENTS_KEY);
    if (!saved) return DEFAULT_RECENTS;
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
  return DEFAULT_RECENTS;
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

function GearIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M9.7 3.7h4.6l.5 2a7 7 0 0 1 1.4.8l2-.6 2.3 4-1.5 1.5a7 7 0 0 1 0 1.6l1.5 1.5-2.3 4-2-.6a7 7 0 0 1-1.4.8l-.5 2H9.7l-.5-2a7 7 0 0 1-1.4-.8l-2 .6-2.3-4L5 13a7 7 0 0 1 0-1.6l-1.5-1.5 2.3-4 2 .6a7 7 0 0 1 1.4-.8z" />
      <circle cx="12" cy="12.2" r="2.6" />
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

function ProfileView({
  profile,
  activeTab,
  onTabChange,
}: {
  profile: ProfessorProfile;
  activeTab: 'reviews' | 'trace';
  onTabChange: (tab: 'reviews' | 'trace') => void;
}) {
  const [reviewSort, setReviewSort] = useState<'newest' | 'highest' | 'lowest'>('newest');
  const reviews = profile.sources.rmp.reviews;
  const orderedReviews = [...reviews].sort((a, b) => {
    if (reviewSort === 'highest') return b.quality - a.quality;
    if (reviewSort === 'lowest') return a.quality - b.quality;
    return Date.parse(b.date) - Date.parse(a.date);
  });
  const survey = profile.sources.survey;
  const distribution = survey.ratingDistribution;
  const totalEvaluations = Object.values(distribution).reduce((sum, value) => sum + value, 0);

  return (
    <>
      <nav className="profile-tabs" aria-label="Professor information">
        <button className={activeTab === 'reviews' ? 'active' : ''} onClick={() => onTabChange('reviews')} type="button">Reviews</button>
        <button className={activeTab === 'trace' ? 'active' : ''} onClick={() => onTabChange('trace')} type="button">TRACE Data</button>
        <button className="disabled-tab" type="button" disabled>Courses</button>
      </nav>

      {activeTab === 'reviews' ? (
        <section className="profile-content">
          <div className="content-heading">
            <div>
              <h1>Student Reviews <span className="count">({profile.summary.numComments})</span></h1>
              <p>Written feedback from Rate My Professors</p>
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
          {orderedReviews.length ? (
            <div className="review-list">
              {orderedReviews.map((review, index) => <ReviewCard key={`${review.date}-${index}`} review={review} />)}
            </div>
          ) : (
            <p className="profile-empty">No written reviews are available for this professor yet.</p>
          )}
        </section>
      ) : (
        <section className="profile-content trace-content">
          <div className="content-heading trace-heading">
            <div>
              <h1>TRACE Evaluation Results <span className="info-dot" title="Student evaluation data available for this professor">i</span></h1>
              <p>{survey.available ? `${survey.numRatings.toLocaleString()} responses` : 'Student evaluation data'}</p>
            </div>
            {survey.rating != null && <strong className="trace-total">{survey.rating.toFixed(1)}<small> / 5</small></strong>}
          </div>
          {survey.available ? (
            <>
              <div className="trace-summary">
                <span>Overall</span>
                <div className="trace-bar"><span style={{ width: `${((survey.rating ?? 0) / 5) * 100}%` }} /></div>
                <strong>{survey.rating?.toFixed(1) ?? '—'}</strong>
              </div>
              <div className="distribution-heading">Rating distribution <span>{totalEvaluations.toLocaleString()} responses</span></div>
              {[5, 4, 3, 2, 1].map((score) => {
                const count = distribution[String(score) as keyof typeof distribution] ?? 0;
                const percent = totalEvaluations ? (count / totalEvaluations) * 100 : 0;
                return (
                  <div className="distribution-row" key={score}>
                    <span>{score} ★</span>
                    <div className="trace-bar"><span style={{ width: `${percent}%` }} /></div>
                    <strong>{count.toLocaleString()}</strong>
                  </div>
                );
              })}
              <p className="trace-note">Detailed category scores aren’t included in the available evaluation data.</p>
            </>
          ) : (
            <p className="profile-empty">TRACE evaluation data isn’t available for this professor yet.</p>
          )}
        </section>
      )}
    </>
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
  const [profileTab, setProfileTab] = useState<'reviews' | 'trace'>('reviews');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const normalized = query.trim();
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
          if (active) setResults(matches);
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
    setProfileTab('reviews');
    setProfileLoading(true);
    fetchProfessorProfile(professor.slug)
      .then(setProfile)
      .catch((err: unknown) => setProfileError(
        isUnavailable(err)
          ? 'Professor details are temporarily unavailable. Check your connection and try again.'
          : 'Could not load professor details. Please try again.',
      ))
      .finally(() => setProfileLoading(false));
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
        <button
          className="icon-button settings-button"
          type="button"
          aria-label="Settings"
          title="Settings"
        >
          <GearIcon />
        </button>
      </header>

      {selectedProfessor ? (
        <>
          <div className="profile-titlebar">
            <button className="back-button" type="button" aria-label="Back to search" onClick={() => {
              setSelectedProfessor(null);
              setProfile(null);
            }}><ChevronIcon /></button>
            <div className="profile-identity">
              {profile?.identity.imageUrl ? <img src={profile.identity.imageUrl} alt="" /> : <span className="avatar large" />}
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
          ) : profile ? <ProfileView profile={profile} activeTab={profileTab} onTabChange={setProfileTab} /> : null}
        </>
      ) : <main className="body">
        <form
          className="search-box"
          role="search"
          onSubmit={(event) => {
            event.preventDefault();
            if (results[0]) openProfessor(results[0]);
          }}
        >
          <SearchIcon />
          <input
            ref={inputRef}
            autoFocus
            aria-label="Search professor, course, or department"
            placeholder="Search professor, course, or department..."
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          {query && (
            <button
              className="icon-button clear-query"
              type="button"
              aria-label="Clear search"
              onClick={() => {
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
                      onClick={() => setQuery(recent.name)}
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
            ) : results.length > 0 ? (
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
