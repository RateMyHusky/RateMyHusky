import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useBookmarks } from '../context/BookmarksContext';
import type { BookmarkedProfessor, BookmarkedCourse } from '../context/BookmarksContext';
import BookmarkButton from '../components/BookmarkButton';
import StarRating from '../components/StarRating';
import SignInModal from '../components/SignInModal';
import Footer from '../components/Footer';
import { getInitials, splitProfName, stripPrefix } from '../utils/nameUtils';
import './ProfessorCatalog.css';
import './Courses.css';
import './Bookmarks.css';

type Tab = 'all' | 'professors' | 'courses';
type SortKey = 'saved' | 'rating' | 'alpha';

const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: 'saved',  label: 'Recently saved' },
  { value: 'rating', label: 'Highest rated' },
  { value: 'alpha',  label: 'A – Z' },
];

const PREVIEW_ROWS = 2; // per-section preview rows on the All tab
const BATCH_ROWS = 4;   // "Show more" rows per batch on the type tabs (matches catalog pages)

function ratingColor(v: number | null): 'high' | 'mid' | 'low' | 'neutral' {
  if (v === null) return 'neutral';
  if (v >= 4) return 'high';
  if (v >= 3) return 'mid';
  return 'low';
}

const BOOKMARK_ICON = (
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
  </svg>
);

// Exact copy of the catalog grid card (ProfessorCatalog.tsx:756-824), including
// the footer stats row the old bookmarks page dropped.
function ProfCard({ prof, onOpen, onRemove }: { prof: BookmarkedProfessor; onOpen: () => void; onRemove: () => void }) {
  return (
    <div
      className="prof-card"
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={e => e.key === 'Enter' && e.target === e.currentTarget && onOpen()}
    >
      <BookmarkButton itemType="professor" itemKey={prof.slug} size="sm" className="prof-card-bookmark" onToggle={onRemove} />
      <div className="prof-card-photo">
        <div className="prof-avatar">
          {prof.imageUrl ? (
            <img
              src={prof.imageUrl}
              alt=""
              className="prof-avatar-img"
              style={{ objectPosition: `${prof.focusX ?? 50}% ${prof.focusY ?? 30}%` }}
              onError={(e) => {
                const target = e.currentTarget;
                target.style.display = 'none';
                const fallback = target.parentElement?.querySelector('.prof-avatar-initials') as HTMLElement;
                if (fallback) fallback.style.display = 'flex';
              }}
            />
          ) : null}
          <span className="prof-avatar-initials" style={prof.imageUrl ? { display: 'none' } : undefined}>
            {getInitials(prof.name)}
          </span>
        </div>
      </div>
      <div className="prof-card-info">
        <div className="prof-card-info-top">
          <h3 className="prof-name">
            {(() => {
              const [first, rest] = splitProfName(stripPrefix(prof.name));
              return rest ? <>{first}<br />{rest}</> : first;
            })()}
          </h3>
          <div className="prof-card-rating-row">
            <span className="prof-avg-num">{prof.avgRating != null ? prof.avgRating.toFixed(1) : 'N/A'}</span>
            <StarRating rating={prof.avgRating ?? 0} size="sm" />
          </div>
        </div>
        <span className="prof-college">{prof.college}</span>
        <span className="prof-dept-label">{prof.department}</span>
        <div className="prof-sub-ratings">
          <div className="sub-rating-item" data-color={ratingColor(prof.rmpRating)}>
            <span className="sub-rating-val">{prof.rmpRating != null ? prof.rmpRating.toFixed(1) : '—'}</span>
            <span className="sub-rating-lbl">RMP</span>
          </div>
          <div className="sub-rating-item" data-color={ratingColor(prof.traceRating)}>
            <span className="sub-rating-val">{prof.traceRating != null ? prof.traceRating.toFixed(1) : '—'}</span>
            <span className="sub-rating-lbl">Students</span>
          </div>
        </div>
        <div className="prof-card-footer">
          <span className="prof-rating-count">{prof.totalReviews.toLocaleString()} ratings</span>
          <span className="prof-rating-count prof-rating-count--center">{prof.totalComments.toLocaleString()} comments</span>
          <span className="prof-rating-count">{prof.wouldTakeAgainPct != null ? `${Math.round(prof.wouldTakeAgainPct)}% again` : '—'}</span>
        </div>
      </div>
    </div>
  );
}

// Exact copy of the course catalog card (Courses.tsx:478-505).
function CourseCard({ course, onOpen, onRemove }: { course: BookmarkedCourse; onOpen: () => void; onRemove: () => void }) {
  return (
    <div
      className="prof-card course-card"
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={e => e.key === 'Enter' && e.target === e.currentTarget && onOpen()}
    >
      <BookmarkButton itemType="course" itemKey={course.code} size="sm" className="prof-card-bookmark" onToggle={onRemove} />
      <div className="course-card-header">
        <span className="course-card-code">{course.code}</span>
      </div>
      <div className="prof-body">
        <h3 className="prof-name">{course.name}</h3>
        <p className="prof-dept">{course.department}</p>
        <div className="prof-rating-row">
          {course.avgRating != null ? (
            <>
              <span className="prof-avg-num">{course.avgRating.toFixed(2)}</span>
              <StarRating rating={course.avgRating} size="sm" />
            </>
          ) : (
            <span className="prof-avg na">N/A</span>
          )}
        </div>
      </div>
    </div>
  );
}

export default function Bookmarks() {
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();
  const { bookmarkedProfessors, bookmarkedCourses, loading, toggleBookmark } = useBookmarks();
  const [showSignIn, setShowSignIn] = useState(false);

  const [pending, setPending] = useState<{ type: 'professor' | 'course'; key: string; label: string } | null>(null);
  const pendingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const commitRef = useRef<() => void>(() => {});

  // Keep the latest commit closure available to the timer and the unmount flush.
  useEffect(() => {
    commitRef.current = () => {
      if (pendingTimer.current) {
        clearTimeout(pendingTimer.current);
        pendingTimer.current = null;
      }
      if (pending) void toggleBookmark(pending.type, pending.key);
      setPending(null);
    };
  });

  // Leaving the page commits any pending removal.
  useEffect(() => () => commitRef.current(), []);

  const requestRemove = (type: 'professor' | 'course', key: string, label: string) => {
    commitRef.current(); // a second removal commits the previous one immediately
    setPending({ type, key, label });
    pendingTimer.current = setTimeout(() => commitRef.current(), 5000);
  };

  const undoRemove = () => {
    if (pendingTimer.current) {
      clearTimeout(pendingTimer.current);
      pendingTimer.current = null;
    }
    setPending(null);
  };

  const visibleProfessors = useMemo(
    () => bookmarkedProfessors.filter(p => !(pending?.type === 'professor' && pending.key === p.slug)),
    [bookmarkedProfessors, pending]
  );
  const visibleCourses = useMemo(
    () => bookmarkedCourses.filter(c => !(pending?.type === 'course' && pending.key === c.code)),
    [bookmarkedCourses, pending]
  );

  const [tab, setTab] = useState<Tab>('all');
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<SortKey>('saved');
  const [shownBatches, setShownBatches] = useState({ professors: 1, courses: 1 });

  // Measure the grid's column count so preview/batch sizes are always a
  // multiple of it and every row renders full, whatever the device width
  // (same trick as ProfessorCatalog.tsx). React 19 cleanup refs let the
  // same callback observe every grid on the page.
  const [numCols, setNumCols] = useState(4);
  const gridRef = useCallback((node: HTMLDivElement) => {
    const update = () => {
      setNumCols(window.getComputedStyle(node).gridTemplateColumns.split(' ').length);
    };
    const observer = new ResizeObserver(update);
    observer.observe(node);
    update();
    return () => observer.disconnect();
  }, []);
  const preview = numCols * PREVIEW_ROWS;
  const batch = numCols * BATCH_ROWS;
  const [sortOpen, setSortOpen] = useState(false);
  const sortRef = useRef<HTMLDivElement>(null);
  const sortPopRef = useRef<HTMLDivElement>(null);

  // ≤540px the sort popover is portaled to document.body as a bottom sheet
  // (see below) so it can escape .bm-controls' stacking context and sit
  // above the fixed navbar with a full-viewport dimmed overlay.
  const [isMobileSort, setIsMobileSort] = useState(() => window.matchMedia('(max-width: 540px)').matches);
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 540px)');
    const onChange = (e: MediaQueryListEvent) => setIsMobileSort(e.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  // Close the sort popover on outside click (same pattern as CollegeFilter).
  // Checks sortPopRef too since the popover content may be portaled outside
  // sortRef's subtree on mobile.
  useEffect(() => {
    if (!sortOpen) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      if (sortRef.current?.contains(target)) return;
      if (sortPopRef.current?.contains(target)) return;
      setSortOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [sortOpen]);

  const q = query.trim().toLowerCase();

  const profs = useMemo(() => {
    let list = visibleProfessors;
    if (q) list = list.filter(p => `${p.name} ${p.department} ${p.college}`.toLowerCase().includes(q));
    if (sort === 'rating') list = [...list].sort((a, b) => (b.avgRating ?? -1) - (a.avgRating ?? -1));
    else if (sort === 'alpha') list = [...list].sort((a, b) => stripPrefix(a.name).localeCompare(stripPrefix(b.name)));
    return list; // 'saved' keeps server order (bookmarkedAt desc)
  }, [visibleProfessors, q, sort]);

  const courses = useMemo(() => {
    let list = visibleCourses;
    if (q) list = list.filter(c => `${c.code} ${c.name} ${c.department}`.toLowerCase().includes(q));
    if (sort === 'rating') list = [...list].sort((a, b) => (b.avgRating ?? -1) - (a.avgRating ?? -1));
    else if (sort === 'alpha') list = [...list].sort((a, b) => a.code.localeCompare(b.code));
    return list;
  }, [visibleCourses, q, sort]);

  const switchTab = (t: Tab) => {
    setTab(t);
    setShownBatches({ professors: 1, courses: 1 });
  };

  if (authLoading) return null;

  if (!user) {
    return (
      <div className="catalog-page bookmarks-page">
        <div className="bm-signin-wrap">
          <div className="bm-signin-gate">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="bm-lock-icon">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
            </svg>
            <p>Sign in with your <span className="husky-email">husky.neu.edu</span> account to view your bookmarks.</p>
            <button className="bm-signin-btn" onClick={() => setShowSignIn(true)}>Sign In</button>
          </div>
        </div>
        <SignInModal open={showSignIn} onClose={() => setShowSignIn(false)} />
        <Footer />
      </div>
    );
  }

  if (loading) {
    return (
      <div className="catalog-page bookmarks-page">
        <div className="catalog-header">
          <h1 className="catalog-title">Bookmarks</h1>
          <span className="catalog-count">…</span>
        </div>
        <div className="bm-content">
          <div className="catalog-grid">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="prof-card skeleton" />
            ))}
          </div>
        </div>
        <Footer />
      </div>
    );
  }

  const total = visibleProfessors.length + visibleCourses.length;

  // Shared popover content: rendered in place under the Sort button on
  // desktop, portaled to document.body as a bottom sheet on mobile.
  const sortPopContent = (
    <>
      <div className="bm-sort-overlay" onClick={() => setSortOpen(false)} />
      <div className="bm-sort-pop" role="listbox" ref={sortPopRef}>
        {SORT_OPTIONS.map(opt => (
          <button
            key={opt.value}
            role="option"
            aria-selected={sort === opt.value}
            className={`bm-sort-opt${sort === opt.value ? ' selected' : ''}`}
            onClick={() => { setSort(opt.value); setSortOpen(false); }}
          >
            {opt.label}
            <span style={{ visibility: sort === opt.value ? 'visible' : 'hidden' }}>✓</span>
          </button>
        ))}
      </div>
    </>
  );

  return (
    <div className="catalog-page bookmarks-page">
      <div className="catalog-header">
        <h1 className="catalog-title">Bookmarks</h1>
        <span className="catalog-count">{total} saved</span>
      </div>

      {total === 0 ? (
        <div className="catalog-empty">
          <div className="bm-empty-icon">{BOOKMARK_ICON}</div>
          <p className="bm-empty-title">You haven't bookmarked anything yet</p>
          <p className="bm-empty-hint">Tap the bookmark flag on any professor or course card to save it here for quick access.</p>
          <div className="bm-empty-ctas">
            <Link to="/professors" className="clear-btn prominent">Browse Professors</Link>
            <Link to="/courses" className="clear-btn prominent secondary">Browse Courses</Link>
          </div>
        </div>
      ) : (
        <>
          <div className="bm-controls">
            <div className="bm-tabs" role="tablist">
              <button role="tab" aria-selected={tab === 'all'} className={`bm-tab${tab === 'all' ? ' active' : ''}`} onClick={() => switchTab('all')}>
                All<span className="bm-tab-count">{total}</span>
              </button>
              <button role="tab" aria-selected={tab === 'professors'} className={`bm-tab${tab === 'professors' ? ' active' : ''}`} onClick={() => switchTab('professors')}>
                Professors<span className="bm-tab-count">{visibleProfessors.length}</span>
              </button>
              <button role="tab" aria-selected={tab === 'courses'} className={`bm-tab${tab === 'courses' ? ' active' : ''}`} onClick={() => switchTab('courses')}>
                Courses<span className="bm-tab-count">{visibleCourses.length}</span>
              </button>
            </div>
            <div className="bm-toolbar">
              <input
                type="text"
                className="bm-search"
                placeholder="Search your bookmarks…"
                aria-label="Search your bookmarks"
                value={query}
                onChange={e => setQuery(e.target.value)}
              />
              <div className={`bm-sort${sortOpen ? ' open' : ''}`} ref={sortRef}>
                <button className="bm-sort-btn" aria-haspopup="listbox" aria-expanded={sortOpen} onClick={() => setSortOpen(o => !o)}>
                  <span className="filter-toggle-icon">
                    <span className="filter-toggle-bar" />
                    <span className="filter-toggle-bar" />
                    <span className="filter-toggle-bar" />
                  </span>
                  Sort
                </button>
                {sortOpen && !isMobileSort && sortPopContent}
              </div>
            </div>
          </div>
          {sortOpen && isMobileSort && createPortal(sortPopContent, document.body)}

          <div className="bm-content">
            {tab === 'all' && (
              q && profs.length === 0 && courses.length === 0 ? (
                <div className="catalog-empty">
                  <div className="bm-empty-icon">{BOOKMARK_ICON}</div>
                  <p className="bm-empty-title">No bookmarks match your search</p>
                  <p className="bm-empty-hint">Try a different name, course code, or department.</p>
                  <div className="bm-empty-ctas">
                    <button className="clear-btn prominent" onClick={() => setQuery('')}>Clear search</button>
                  </div>
                </div>
              ) : (
                <>
                  {(profs.length > 0 || (!q && visibleProfessors.length === 0)) && (
                    <section>
                      <div className="bm-section-head">
                        <h2 className="bm-section-title">Professors</h2>
                        <span className="bm-section-count">{profs.length}</span>
                        {!q && profs.length > preview && (
                          <button className="bm-showall" onClick={() => switchTab('professors')}>Show all {profs.length} →</button>
                        )}
                      </div>
                      {visibleProfessors.length === 0 ? (
                        <div className="bm-mini-empty">No professors saved yet — <Link to="/professors">browse professors</Link> and tap the flag to add one.</div>
                      ) : (
                        <div className="catalog-grid" ref={gridRef}>
                          {(q ? profs : profs.slice(0, preview)).map(prof => (
                            <ProfCard key={prof.slug} prof={prof} onOpen={() => navigate(`/professors/${prof.slug}`)} onRemove={() => requestRemove('professor', prof.slug, stripPrefix(prof.name))} />
                          ))}
                        </div>
                      )}
                    </section>
                  )}
                  {(courses.length > 0 || (!q && visibleCourses.length === 0)) && (
                    <section>
                      <div className="bm-section-head">
                        <h2 className="bm-section-title">Courses</h2>
                        <span className="bm-section-count">{courses.length}</span>
                        {!q && courses.length > preview && (
                          <button className="bm-showall" onClick={() => switchTab('courses')}>Show all {courses.length} →</button>
                        )}
                      </div>
                      {visibleCourses.length === 0 ? (
                        <div className="bm-mini-empty">No courses saved yet — <Link to="/courses">browse courses</Link> and tap the flag to add one.</div>
                      ) : (
                        <div className="catalog-grid" ref={gridRef}>
                          {(q ? courses : courses.slice(0, preview)).map(course => (
                            <CourseCard key={course.code} course={course} onOpen={() => navigate(`/courses/${course.code.toLowerCase()}`)} onRemove={() => requestRemove('course', course.code, course.code)} />
                          ))}
                        </div>
                      )}
                    </section>
                  )}
                </>
              )
            )}

            {tab === 'professors' && (
              visibleProfessors.length === 0 ? (
                <div className="catalog-empty">
                  <div className="bm-empty-icon">{BOOKMARK_ICON}</div>
                  <p className="bm-empty-title">No saved professors yet</p>
                  <p className="bm-empty-hint">Tap the bookmark flag on any professor card to keep them here.</p>
                  <div className="bm-empty-ctas">
                    <Link to="/professors" className="clear-btn prominent">Browse Professors</Link>
                  </div>
                </div>
              ) : profs.length === 0 ? (
                <div className="catalog-empty">
                  <div className="bm-empty-icon">{BOOKMARK_ICON}</div>
                  <p className="bm-empty-title">No bookmarks match your search</p>
                  <p className="bm-empty-hint">Try a different name, course code, or department.</p>
                  <div className="bm-empty-ctas">
                    <button className="clear-btn prominent" onClick={() => setQuery('')}>Clear search</button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="catalog-grid" ref={gridRef}>
                    {(q ? profs : profs.slice(0, shownBatches.professors * batch)).map(prof => (
                      <ProfCard key={prof.slug} prof={prof} onOpen={() => navigate(`/professors/${prof.slug}`)} onRemove={() => requestRemove('professor', prof.slug, stripPrefix(prof.name))} />
                    ))}
                  </div>
                  {!q && (
                    shownBatches.professors * batch >= profs.length ? (
                      profs.length > batch && (
                        <div className="bm-loadmore-row"><span className="bm-viewing">Viewing all {profs.length}</span></div>
                      )
                    ) : (
                      <div className="bm-loadmore-row">
                        <span className="bm-viewing">Viewing {Math.min(shownBatches.professors * batch, profs.length)} of {profs.length}</span>
                        <button
                          className="clear-btn prominent secondary"
                          onClick={() => setShownBatches(s => ({ ...s, professors: s.professors + 1 }))}
                        >
                          Show {Math.min(batch, profs.length - shownBatches.professors * batch)} more
                        </button>
                      </div>
                    )
                  )}
                </>
              )
            )}

            {tab === 'courses' && (
              visibleCourses.length === 0 ? (
                <div className="catalog-empty">
                  <div className="bm-empty-icon">{BOOKMARK_ICON}</div>
                  <p className="bm-empty-title">No saved courses yet</p>
                  <p className="bm-empty-hint">Tap the bookmark flag on any course card to keep it here.</p>
                  <div className="bm-empty-ctas">
                    <Link to="/courses" className="clear-btn prominent">Browse Courses</Link>
                  </div>
                </div>
              ) : courses.length === 0 ? (
                <div className="catalog-empty">
                  <div className="bm-empty-icon">{BOOKMARK_ICON}</div>
                  <p className="bm-empty-title">No bookmarks match your search</p>
                  <p className="bm-empty-hint">Try a different name, course code, or department.</p>
                  <div className="bm-empty-ctas">
                    <button className="clear-btn prominent" onClick={() => setQuery('')}>Clear search</button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="catalog-grid" ref={gridRef}>
                    {(q ? courses : courses.slice(0, shownBatches.courses * batch)).map(course => (
                      <CourseCard key={course.code} course={course} onOpen={() => navigate(`/courses/${course.code.toLowerCase()}`)} onRemove={() => requestRemove('course', course.code, course.code)} />
                    ))}
                  </div>
                  {!q && (
                    shownBatches.courses * batch >= courses.length ? (
                      courses.length > batch && (
                        <div className="bm-loadmore-row"><span className="bm-viewing">Viewing all {courses.length}</span></div>
                      )
                    ) : (
                      <div className="bm-loadmore-row">
                        <span className="bm-viewing">Viewing {Math.min(shownBatches.courses * batch, courses.length)} of {courses.length}</span>
                        <button
                          className="clear-btn prominent secondary"
                          onClick={() => setShownBatches(s => ({ ...s, courses: s.courses + 1 }))}
                        >
                          Show {Math.min(batch, courses.length - shownBatches.courses * batch)} more
                        </button>
                      </div>
                    )
                  )}
                </>
              )
            )}
          </div>
        </>
      )}
      {pending && (
        <div className="bm-snackbar" role="status">
          <span className="bm-snackbar-text">Removed {pending.label}</span>
          <button className="bm-undo" onClick={undoRemove}>Undo</button>
        </div>
      )}
      <Footer />
    </div>
  );
}
