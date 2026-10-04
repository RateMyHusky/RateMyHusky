import { useState, useEffect, useRef, useCallback, useMemo, useLayoutEffect } from 'react';
import { useParams, Link, useLocation } from 'react-router-dom';
import Footer from '../components/Footer';
import NotFound from './NotFound';
import LoadError from '../components/LoadError';
import Dropdown from '../components/Dropdown';
import StarRating from '../components/StarRating';
import RatingBar from '../components/RatingBar';
import Breadcrumbs from '../components/Breadcrumbs';
import Seo from '../components/Seo';
import { fetchProfessorFull } from '../api/api';
import type { ProfessorPage, ProfessorCourse, RatingDistribution, RedditMention } from '../api/api';
import { SHOW_SURVEY_STATS } from '../config';
import { termSortKey } from '../utils/termUtils';
import { isPinned, pinnedFirst } from '../utils/askPinMatch';
import BookmarkButton from '../components/BookmarkButton';
import neuIcon from '../assets/neu-circle-icon.png';
import './Professor.css';

/* ───────── animated number counter ───────── */
const AnimatedNumber = ({
  value, decimals = 2, suffix = '',
}: { value: number | null; decimals?: number; suffix?: string }) => {
  const [display, setDisplay] = useState(value === null ? '—' : '0' + suffix);
  const hasAnimated = useRef(false);
  const prevValue = useRef<number | null>(null);
  const ref = useRef<HTMLSpanElement>(null);

  const animate = useCallback((from: number, to: number) => {
    const duration = 1000;
    const start = performance.now();
    const step = (now: number) => {
      const t = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - t, 3);
      const current = from + (to - from) * eased;
      setDisplay(current.toFixed(decimals) + suffix);
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }, [decimals, suffix]);

  useEffect(() => {
    if (value === null) {
      prevValue.current = null;
      return;
    }
    if (!hasAnimated.current) return;
    if (prevValue.current !== value) {
      animate(prevValue.current || 0, value);
      prevValue.current = value;
    }
  }, [value, animate]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(([e]) => { 
      if (e.isIntersecting && !hasAnimated.current && value !== null) { 
        hasAnimated.current = true;
        animate(0, value);
        prevValue.current = value;
        obs.disconnect(); 
      } 
    }, { threshold: 0.5 });
    obs.observe(el);
    return () => obs.disconnect();
  }, [animate, value]);

  return <span ref={ref}>{display}</span>;
};

/* ───────── term collapse chevron ───────── */
const TermCollapseChevron = () => {
  const ref = useRef<SVGSVGElement>(null);
  const [hasLeftSibling, setHasLeftSibling] = useState(false);

  useLayoutEffect(() => {
    const svg = ref.current;
    if (!svg) return;
    const wrapper = svg.parentElement;
    if (!wrapper) return;
    const check = () => {
      const prev = wrapper.previousElementSibling as HTMLElement | null;
      if (prev) {
        const wTop = wrapper.getBoundingClientRect().top;
        const prevTop = prev.getBoundingClientRect().top;
        setHasLeftSibling(Math.abs(prevTop - wTop) < 5);
      } else {
        setHasLeftSibling(false);
      }
    };
    check();
    const frame = requestAnimationFrame(check);
    const container = wrapper.parentElement;
    const ro = container ? new ResizeObserver(check) : null;
    if (container && ro) ro.observe(container);
    return () => { ro?.disconnect(); cancelAnimationFrame(frame); };
  });

  return hasLeftSibling ? (
    <svg ref={ref} className="prof-term-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="15 18 9 12 15 6" /></svg>
  ) : (
    <svg ref={ref} className="prof-term-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="18 15 12 9 6 15" /></svg>
  );
};

/* ───────── sort / filter options ───────── */
const sortOptions = [
  { value: 'newest', label: 'Newest First' },
  { value: 'oldest', label: 'Oldest First' },
  { value: 'highest', label: 'Highest Rated' },
  { value: 'lowest', label: 'Lowest Rated' },
];

const redditSentimentOptions = [
  { value: 'all', label: 'All Sentiment' },
  { value: 'positive', label: 'Positive' },
  { value: 'neutral', label: 'Neutral' },
  { value: 'negative', label: 'Negative' },
];

// Strictly extract "Season Year" from messy term titles
const cleanTerm = (t: string): string => {
  // Match terms like "Fall 2025", "Fall A 2025", "Summer 2 2025"
  const fullMatch = t.match(/(Spring|Fall|Summer|Winter)\s*([A-Z]|\d)?\s*(20\d{2})/i);
  if (fullMatch) {
    const season = fullMatch[1].charAt(0).toUpperCase() + fullMatch[1].slice(1).toLowerCase();
    const modifier = (fullMatch[2] ?? '').trim();
    const year = fullMatch[3];
    return modifier ? `${season} ${modifier} ${year}` : `${season} ${year}`;
  }
  const seasonMatch = t.match(/(Spring|Fall|Summer|Winter)/i);
  if (!seasonMatch) return t.trim();
  const season = seasonMatch[1].charAt(0).toUpperCase() + seasonMatch[1].slice(1).toLowerCase();
  // Fallback: extract year from 6-digit term codes like "202130" → "2021"
  const termCodeMatch = t.match(/(20\d{2})\d{2}/);
  if (termCodeMatch) return `${season} ${termCodeMatch[1]}`;
  return season;
};

const formatReviewDate = (dateStr: string) => {
  if (!dateStr) return '';
  // Convert "2022-12-11 18:36:58 +0000 UTC" to "2022-12-11T18:36:58Z"
  const normalized = dateStr.replace(' +0000 UTC', '').replace(' ', 'T') + 'Z';
  const date = new Date(normalized);
  if (isNaN(date.getTime())) return dateStr;
  return date.toLocaleDateString('en-US', {
    month: 'long',
    day: 'numeric',
    year: 'numeric'
  });
};

const GRADE_ORDER = ['A+','A','A-','B+','B','B-','C+','C','C-','D+','D','D-','F','W','WF','P','NP','I'];
const GRADE_COLORS: Record<string, string> = {
  'A+':'#1a9850','A':'#27ae60','A-':'#66bd63',
  'B+':'#a6d96a','B':'#d4e858','B-':'#fee08b',
  'C+':'#fdae61','C':'#f39c12','C-':'#e67e22',
  'D+':'#e74c3c','D':'#d73027','D-':'#c0392b',
  'F':'#a50026','W':'#7f8c8d','WF':'#636e72','P':'#2980b9','NP':'#8e44ad','I':'#999',
};

/* ───────── near-duplicate detection ───────── */
function normalizeText(s: string): string {
  return s.toLowerCase().replace(/\s+/g, ' ').trim();
}

function deduplicateByText<T>(items: T[], getText: (item: T) => string): T[] {
  const seen = new Set<string>();
  const result: T[] = [];
  for (const item of items) {
    const raw = getText(item);
    if (!raw.trim()) { result.push(item); continue; }
    // Use a truncated normalized form as a fingerprint — catches exact and near-exact dupes
    const norm = normalizeText(raw);
    // Check exact match first
    if (seen.has(norm)) continue;
    // Check prefix-based match (catches 95%+ similar: same text with minor trailing differences)
    const prefix = norm.slice(0, Math.floor(norm.length * 0.9));
    let isDupe = false;
    for (const s of seen) {
      if (s.startsWith(prefix) || norm.startsWith(s.slice(0, Math.floor(s.length * 0.9)))) {
        // Confirm length similarity (within 10%)
        const ratio = Math.min(s.length, norm.length) / Math.max(s.length, norm.length);
        if (ratio >= 0.9) { isDupe = true; break; }
      }
    }
    if (!isDupe) {
      seen.add(norm);
      result.push(item);
    }
  }
  return result;
}

/* Display names for summary.bySource keys; an unlisted source shows its key. */
const SOURCE_LABELS: Record<string, string> = { rmp: 'RMP' };

/* A review's course as the backend groups it (whitespace stripped, uppercased); codes the backend rejects never appear in courses[]. */
const courseCode = (raw: string) => raw.replace(/\s+/g, '').toUpperCase();

const STARS = ['5', '4', '3', '2', '1'] as const;
const emptyDistribution = (): RatingDistribution => ({ '1': 0, '2': 0, '3': 0, '4': 0, '5': 0 });

const difficultyColor = (d: number) => {
  if (d <= 1.5) return '#27ae60';
  if (d <= 2.5) return '#66bd63';
  if (d <= 3.0) return '#f39c12';
  if (d <= 3.5) return '#e67e22';
  if (d <= 4.0) return '#e74c3c';
  return '#c0392b';
};

const COURSES_COLLAPSED_LIMIT = 5;
const MAX_VISIBLE_TERMS = 3;

const Professor = () => {
  const { slug } = useParams<{ slug: string }>();
  const reviewsRef = useRef<HTMLElement>(null);
  const chartsRef = useRef<HTMLElement>(null);
  const gradesRef = useRef<HTMLDivElement>(null);
  const reviewTabsRef = useRef<HTMLDivElement>(null);

  const [profile, setProfile] = useState<ProfessorPage | null>(null);
  const [loadError, setLoadError] = useState<'not_found' | 'failed' | null>(null);
  const [loading, setLoading] = useState(true);
  const [redditSentiment, setRedditSentiment] = useState('all');
  const [redditSearch, setRedditSearch] = useState('');
  const [visibleRedditMentions, setVisibleRedditMentions] = useState(10);
  const [reviewTab, setReviewTab] = useState<'rmp' | 'reddit'>('rmp');
  const [sortBy, setSortBy] = useState('newest');
  const [visibleReviews, setVisibleReviews] = useState(10);
  const [selectedCourses, setSelectedCourses] = useState<Set<string>>(new Set());
  const [showBackToTop, setShowBackToTop] = useState(false);
  const [gradesAnimated, setGradesAnimated] = useState(false);
  const [reviewPillStyle, setReviewPillStyle] = useState({ left: 0, width: 0, opacity: 0 });
  const [isReviewPillReady, setIsReviewPillReady] = useState(false);
  const [showAllCourses, setShowAllCourses] = useState(false);
  const [expandedTerms, setExpandedTerms] = useState<Set<string>>(new Set());
  const [closingTerms, setClosingTerms] = useState<Set<string>>(new Set());
  const [isImageModalOpen, setIsImageModalOpen] = useState(false);
  const [showCourseTip, setShowCourseTip] = useState(() => localStorage.getItem('prof_course_tip_dismissed') !== '1');

  const location = useLocation();
  // Ask pins arrive via navigation state from a clicked citation. Keyed by askedAt so a new
  // question replaces old pins; normal navigation (no askPins) leaves this null.
  const [pinnedSources, setPinnedSources] = useState<{ source: string | null; snippet: string }[]>(
    () => {
      const st = location.state as { askPins?: { sources: { source: string | null; snippet: string }[] } } | null;
      return st?.askPins?.sources ?? [];
    }
  );
  // Sentinel 0 (never a real Date.now() askedAt) so the apply-pins effect's "already applied"
  // guard is false on first mount and actually performs the tab-switch + scroll. The effect
  // sets this ref to the real askedAt once it applies.
  const pinnedAskedAt = useRef<number>(0);
  // Tracks the askedAt we have already scrolled for, so the scroll fires exactly once per new
  // pin set — even though the apply-guard above trips on the effect's second run.
  const scrolledAskedAt = useRef<number>(0);

  /* ── review pill ── */
  const updateReviewPill = useCallback(() => {
    if (!reviewTabsRef.current) return;
    const activeTab = reviewTabsRef.current.querySelector('.prof-review-tab.active') as HTMLElement;
    if (activeTab) {
      setReviewPillStyle({
        left: activeTab.offsetLeft,
        width: activeTab.offsetWidth,
        opacity: 1
      });
    }
  }, []);

  useLayoutEffect(() => {
    if (!loading) {
      updateReviewPill();
    }
  }, [reviewTab, updateReviewPill, loading]);

  useEffect(() => {
    const container = reviewTabsRef.current;
    if (!container || loading) return;

    updateReviewPill();
    const timer = setTimeout(() => setIsReviewPillReady(true), 150);

    const observer = new ResizeObserver(() => {
      setIsReviewPillReady(false);
      updateReviewPill();
      setTimeout(() => setIsReviewPillReady(true), 50);
    });

    observer.observe(container);
    return () => {
      clearTimeout(timer);
      observer.disconnect();
    };
  }, [updateReviewPill, loading]);

  /* ── load: one round-trip, the same payload for every visitor ── */
  useEffect(() => {
    if (!slug) { setLoading(false); setLoadError('not_found'); return; }
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    fetchProfessorFull(slug).then((res) => {
      if (cancelled) return;
      if (res.ok) { setProfile(res.data); setSelectedCourses(new Set(res.data.courses.map(c => c.code))); }
      else setLoadError(res.status === 404 ? 'not_found' : 'failed');
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [slug]);

  const reviews = useMemo(() => profile?.sources.rmp.reviews ?? [], [profile]);
  const redditMentions = useMemo(() => profile?.redditMentions ?? [], [profile]);
  const courses = useMemo(() => profile?.courses ?? [], [profile]);

  /* ── Ask citation pins: switch to the cited source's tab and scroll to reviews ── */
  useEffect(() => {
    const st = location.state as {
      askPins?: {
        askedAt: number;
        clicked: { source: string | null; snippet: string };
        sources: { source: string | null; snippet: string }[];
      };
    } | null;
    const pins = st?.askPins;
    if (!pins) {
      // Arrived without pins (normal nav / breadcrumb / slug change) — clear any stale pins so
      // a previous question's sources don't ride along and mis-pin rows on this page.
      if (pinnedSources.length > 0) {
        setPinnedSources([]);
        pinnedAskedAt.current = 0;
        scrolledAskedAt.current = 0;
      }
      return;
    }

    // Apply the pins + tab switch once per new askedAt.
    if (pins.askedAt !== pinnedAskedAt.current) {
      pinnedAskedAt.current = pins.askedAt;
      setPinnedSources(pins.sources);
      const tab: 'rmp' | 'reddit' = pins.clicked.source === 'rmp' ? 'rmp' : 'reddit';
      setReviewTab(tab);
    }

    // Scroll once per askedAt, but only after reviews have rendered (loading false).
    // On first mount loading starts true; this effect re-runs when it flips false
    // (it's in the deps) and the scroll fires then.
    if (!loading && scrolledAskedAt.current !== pins.askedAt) {
      scrolledAskedAt.current = pins.askedAt;
      setTimeout(() => reviewsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 150);
    }
  }, [location.state, loading]);

  /* ── back to top ── */
  useEffect(() => {
    const handler = () => setShowBackToTop(window.scrollY > 300);
    window.addEventListener('scroll', handler, { passive: true });
    return () => window.removeEventListener('scroll', handler);
  }, []);

  /* ── course filter ── */
  const allCourseCodes = useMemo(() => courses.map(c => c.code), [courses]);

  const unfiltered = allCourseCodes.length === 0 || selectedCourses.size === allCourseCodes.length;
  const noneSelected = allCourseCodes.length > 0 && selectedCourses.size === 0;

  /* Every stored RMP rating in the selection; the card list below dedupes these for display. */
  const rmpRatingsInSelection = useMemo(
    () => unfiltered ? reviews : reviews.filter(r => r.courseCode !== null && selectedCourses.has(r.courseCode)),
    [reviews, selectedCourses, unfiltered]);

  const filteredRmpReviews = useMemo(
    () => deduplicateByText(rmpRatingsInSelection, r => r.comment),
    [rmpRatingsInSelection]);

  /* The cards. Unfiltered: the backend's summary. Filtered: the selected courses[] rows
     combined, weighted by rating count, distributions summed. The per-source hover only
     shows unfiltered, since courses[] rows are already blended. */
  const stats = useMemo(() => {
    if (!profile) return null;
    const s = profile.summary;
    if (noneSelected) {
      return { rating: null, difficulty: null, numRatings: 0,
               breakdown: [] as [string, number][], distribution: emptyDistribution() };
    }
    if (unfiltered) {
      return {
        rating: s.rating, difficulty: s.difficulty, numRatings: s.numRatings,
        breakdown: Object.entries(s.bySource)
          .filter(([, v]) => v.rating !== null)
          .map(([k, v]) => [k, v.rating as number] as [string, number]),
        distribution: profile.sources.rmp.ratingDistribution,
      };
    }
    const rows = courses.filter(c => selectedCourses.has(c.code));
    const weighted = (pick: (c: ProfessorCourse) => number | null) => {
      let sum = 0, n = 0;
      for (const c of rows) {
        const v = pick(c);
        if (v !== null) { sum += v * c.numRatings; n += c.numRatings; }
      }
      return n > 0 ? sum / n : null;
    };
    const distribution = emptyDistribution();
    for (const c of rows) for (const k of STARS) distribution[k] += c.ratingDistribution[k];
    return {
      rating: weighted(c => c.rating),
      difficulty: weighted(c => c.difficulty),
      numRatings: rows.reduce((a, c) => a + c.numRatings, 0),
      breakdown: [] as [string, number][],
      distribution,
    };
  }, [profile, courses, selectedCourses, unfiltered, noneSelected]);

  const ratingDistribution = useMemo(
    () => STARS.map(k => ({ star: Number(k), count: stats?.distribution[k] ?? 0 })), [stats]);
  const maxCount = useMemo(() => Math.max(...ratingDistribution.map(d => d.count), 1), [ratingDistribution]);

  /* Grades over the same rows as the rating distribution. */
  const gradeDistribution = useMemo(() => {
    let counts: Record<string, number> = {};
    if (unfiltered && profile) {
      counts = { ...profile.sources.rmp.gradeDistribution };
    } else if (!noneSelected) {
      rmpRatingsInSelection.forEach(r => {
        const g = r.grade?.trim();
        if (g && g !== 'N/A' && g !== 'Not sure yet' && g !== 'Rather not say') {
          counts[g] = (counts[g] || 0) + 1;
        }
      });
    }
    const total = Object.values(counts).reduce((a, b) => a + b, 0);
    if (total === 0) return [];
    // Find the range of grades that appear and include all in-between
    const presentIndices = GRADE_ORDER.map((g, i) => counts[g] ? i : -1).filter(i => i >= 0);
    if (presentIndices.length === 0) return [];
    const minIdx = Math.min(...presentIndices);
    const maxIdx = Math.max(...presentIndices);
    return GRADE_ORDER.slice(minIdx, maxIdx + 1).map(g => ({
      grade: g,
      count: counts[g] || 0,
      pct: ((counts[g] || 0) / total) * 100,
      color: GRADE_COLORS[g] || '#999'
    }));
  }, [profile, rmpRatingsInSelection, unfiltered, noneSelected]);

  useEffect(() => {
    const el = gradesRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) {
        setGradesAnimated(true);
        obs.disconnect();
      }
    }, { threshold: 0.3 });
    obs.observe(el);
    return () => obs.disconnect();
  }, [profile, gradeDistribution.length]);

  const pinSnippets = useMemo(() => ({
    rmp: pinnedSources.filter((p) => p.source === 'rmp').map((p) => p.snippet),
    // sources with null/unknown source came from Reddit historically (see SOURCE_LABEL default)
    reddit: pinnedSources.filter((p) => p.source === 'reddit' || p.source == null).map((p) => p.snippet),
  }), [pinnedSources]);

  const sortedReviews = useMemo(() => {
    const sorted = [...filteredRmpReviews].sort((a, b) => {
      if (sortBy === 'oldest') return new Date(a.date).getTime() - new Date(b.date).getTime();
      if (sortBy === 'highest') return b.quality - a.quality;
      if (sortBy === 'lowest') return a.quality - b.quality;
      return new Date(b.date).getTime() - new Date(a.date).getTime();
    });
    return pinnedFirst(sorted, (r) => r.comment || '', pinSnippets.rmp);
  }, [filteredRmpReviews, sortBy, pinSnippets.rmp]);

  const redditQuery = redditSearch.trim().toLowerCase();
  const filteredRedditMentions = useMemo(() => {
    const filtered = redditMentions.filter(m =>
      (redditSentiment === 'all' || m.sentiment === redditSentiment) &&
      (redditQuery === '' || m.body.toLowerCase().includes(redditQuery))
    );
    return pinnedFirst(filtered, (m) => m.body || '', pinSnippets.reddit);
  }, [redditMentions, redditSentiment, redditQuery, pinSnippets.reddit]);

  const formatRedditDate = (utc: string | null): string => {
    if (!utc) return '';
    const d = new Date(utc);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
  };

  const sentimentBorderColor = (s: RedditMention['sentiment']): string =>
    s === 'positive' ? '#27ae60' : s === 'negative' ? '#e74c3c' : s === 'neutral' ? '#f39c12' : '#95a5a6';

  // Reddit permalinks are site-relative (e.g. "/r/NEU/comments/..."); allow those and
  // absolute http(s) URLs only, blocking javascript:/data: and other schemes.
  const safeRedditUrl = (url: string | null): string | null => {
    if (!url) return null;
    if (url.startsWith('/')) return `https://www.reddit.com${url}`;
    try {
      return ['http:', 'https:'].includes(new URL(url).protocol) ? url : null;
    } catch { return null; }
  };

  const toggleCourse = (code: string) => {
    setSelectedCourses(prev => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  useEffect(() => { setVisibleReviews(10); }, [sortBy, reviewTab]);
  // Reset visible reviews when course filter changes, but only if the filtered list got smaller
  useEffect(() => { setVisibleReviews(v => Math.min(v, Math.max(10, filteredRmpReviews.length))); }, [selectedCourses.size, filteredRmpReviews.length]);

  useEffect(() => {
    if (!isImageModalOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsImageModalOpen(false);
    };
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    window.addEventListener('keydown', onKeyDown);
    return () => {
      document.body.style.overflow = prevOverflow;
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [isImageModalOpen]);

  if (loading) return (
    <div className="prof-page">
      <div className="prof-loading">
        <div className="prof-loading-spinner" />
        <p>Loading professor data…</p>
      </div>
    </div>
  );

  if (loadError === 'not_found') return <NotFound />;
  if (loadError || !profile || !stats) return <div className="prof-page"><LoadError /></div>;

  const identity = profile.identity;
  const summary = profile.summary;
  const rmp = profile.sources.rmp;

  /* Mirrors render.professor_html's two forms character for character (the crawler copy
     and the page must agree). Two decimals: toFixed(2) reproduces Python's .2f. */
  const seoDescription = rmp.available && rmp.rating !== null
    ? `${identity.name} professor reviews and ratings: ${rmp.rating.toFixed(2)}/5 from ${rmp.numRatings} RMP ratings at Northeastern` +
      (rmp.wouldTakeAgainPct != null ? ` (${rmp.wouldTakeAgainPct}% would take again)` : '') +
      `. RateMyProfessor + Reddit.`
    : `${identity.name}, Northeastern ${identity.department} professor: no Rate My Professors ratings yet. RateMyProfessor + Reddit.`;

  const profCanonical = `https://ratemyhusky.com/professors/${slug}`;
  const profJsonLd = {
    '@context': 'https://schema.org',
    '@type': 'ProfilePage',
    dateModified: new Date().toISOString().slice(0, 10),
    mainEntity: {
      '@type': 'Person',
      name: identity.name,
      jobTitle: 'Professor',
      worksFor: {
        '@type': 'CollegeOrUniversity',
        name: 'Northeastern University',
        sameAs: 'https://www.northeastern.edu',
      },
      knowsAbout: identity.department,
      url: profCanonical,
      ...(identity.imageUrl ? { image: identity.imageUrl } : {}),
      ...(rmp.professorUrl ? { sameAs: [rmp.professorUrl] } : {}),
      // schema.org Person does not support aggregateRating (Google rejects it
      // as an invalid object type in Rich Results), so it is intentionally omitted.
    },
  };
  const profBreadcrumbJsonLd = {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: [
      { '@type': 'ListItem', position: 1, name: 'Home', item: 'https://ratemyhusky.com/' },
      { '@type': 'ListItem', position: 2, name: 'Professors', item: 'https://ratemyhusky.com/professors' },
      { '@type': 'ListItem', position: 3, name: identity.name, item: profCanonical },
    ],
  };

  const renderCourseRow = (c: ProfessorCourse) => {
    const code = c.code;
    const terms = [...new Set((c.terms ?? []).map(cleanTerm))].filter(t => /\b20\d{2}\b/.test(t)).sort((a, b) => termSortKey(b) - termSortKey(a));
    const termsExpanded = expandedTerms.has(code);
    const hiddenTermCount = terms.length - MAX_VISIBLE_TERMS;
    return (
    <div
      key={c.code}
      className={`prof-course-row ${selectedCourses.has(c.code) ? 'selected' : ''}`}
      onClick={() => toggleCourse(c.code)}
    >
      <div className="prof-course-row-main">
        <span className="prof-course-code">{c.code}</span>
        <span className="prof-course-title">{c.name ?? ''}</span>
        <span className="prof-course-terms">{c.numRatings.toLocaleString()} rating{c.numRatings === 1 ? '' : 's'}</span>
      </div>
      {(c.name || terms.length > 0) && (
        <div className="prof-course-lower">
          {terms.length > 0 && (
            <div className="prof-course-term-tags">
              {terms.slice(0, MAX_VISIBLE_TERMS).map(t => <span key={t} className="prof-course-term-tag">{t}</span>)}
              {hiddenTermCount > 0 && !termsExpanded && !closingTerms.has(code) && (
                <span
                  className="prof-course-term-tag prof-course-term-more"
                  onClick={(e) => { e.stopPropagation(); setExpandedTerms(prev => { const next = new Set(prev); next.add(code); return next; }); }}
                >
                  +{hiddenTermCount} more
                </span>
              )}
              {terms.slice(MAX_VISIBLE_TERMS).map((t, i) => {
                const isClosing = closingTerms.has(code);
                const reverseI = hiddenTermCount - 1 - i;
                return <span key={t} className={`prof-course-term-tag prof-course-term-hidden ${termsExpanded || isClosing ? 'visible' : ''} ${isClosing ? 'closing' : ''}`} style={isClosing ? { animationDelay: `${reverseI * 0.04}s` } : termsExpanded ? { animationDelay: `${i * 0.04}s` } : undefined}>{t}</span>;
              })}
              {hiddenTermCount > 0 && (termsExpanded || closingTerms.has(code)) && (
                <span
                  className={`prof-course-term-tag prof-course-term-more ${closingTerms.has(code) ? 'closing' : ''}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    if (closingTerms.has(code)) return;
                    setClosingTerms(prev => { const next = new Set(prev); next.add(code); return next; });
                    setTimeout(() => {
                      setExpandedTerms(prev => { const next = new Set(prev); next.delete(code); return next; });
                      setClosingTerms(prev => { const next = new Set(prev); next.delete(code); return next; });
                    }, hiddenTermCount * 40 + 200);
                  }}
                >
                  <TermCollapseChevron />
                </span>
              )}
            </div>
          )}
          {c.name && (
          <div className="prof-course-view">
            <Link
              to={`/courses/${c.code.toLowerCase()}`}
              state={{ fromPage: { label: identity.name, url: `/professors/${slug}` } }}
              className="prof-course-view-btn"
              onClick={(e) => e.stopPropagation()}
            >
              View Course
            </Link>
          </div>
          )}
        </div>
      )}
    </div>
    );
  };

  return (
    <div className="prof-page">
      <Seo
        title={`${identity.name} Reviews & Ratings — Northeastern ${identity.department}`}
        description={seoDescription}
        canonical={profCanonical}
        image={identity.imageUrl}
        ogType="profile"
        jsonLd={[profJsonLd, profBreadcrumbJsonLd]}
      />
      <header className="prof-hero">
        <div className="prof-hero-bg" style={{ backgroundImage: `url(${neuIcon})` }} />
        <div className="prof-hero-glow" />
        <Breadcrumbs items={[
          { label: 'Professors', to: '/professors' },
          { label: identity.name },
        ]} />
        <div className="prof-hero-inner">
          <div
            className={`prof-avatar ${identity.imageUrl ? 'prof-avatar-clickable' : ''}`}
            onClick={() => {
              if (identity.imageUrl) setIsImageModalOpen(true);
            }}
            role={identity.imageUrl ? 'button' : undefined}
            tabIndex={identity.imageUrl ? 0 : undefined}
            onKeyDown={(e) => {
              if (!identity.imageUrl) return;
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                setIsImageModalOpen(true);
              }
            }}
            aria-label={identity.imageUrl ? `Open larger photo of ${identity.name}` : undefined}
          >
            {identity.imageUrl ? (
              <img
                src={identity.imageUrl}
                alt={identity.name}
                className="prof-avatar-img"
                style={{ objectPosition: `${identity.focusX ?? 50}% ${identity.focusY ?? 30}%` }}
                onError={(e) => {
                  const target = e.currentTarget;
                  target.style.display = 'none';
                  const initials = target.parentElement?.querySelector('.prof-avatar-initials') as HTMLElement;
                  if (initials) initials.style.display = 'flex';
                }}
              />
            ) : null}
            <span
              className="prof-avatar-initials"
              style={identity.imageUrl ? { display: 'none' } : undefined}
            >
              {identity.name.split(' ').map(n => n[0]).join('')}
            </span>
          </div>
          <div className="prof-hero-info">
            <h1 className="prof-name">
              {identity.name}
              <BookmarkButton itemType="professor" itemKey={slug!} size="md" className="prof-hero-bookmark" />
            </h1>
            <p className="prof-dept">{identity.department}</p>
          </div>
        </div>
      </header>

      <section className="prof-stats">
        <div className="prof-stat-card prof-stat-clickable">
          <span className="prof-stat-value">{stats.rating !== null ? <AnimatedNumber value={stats.rating} /> : '—'}</span>
          <span className="prof-stat-label" style={{ display: 'block', textAlign: 'center', position: 'relative' }}>
            Overall Rating
            {stats.breakdown.length > 0 && (
              <svg xmlns="http://www.w3.org/2000/svg" width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ position: 'absolute', top: '50%', transform: 'translateY(-50%)', marginLeft: '4px', opacity: 0.6 }}><circle cx="12" cy="12" r="10"></circle><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>
            )}
          </span>
          <StarRating rating={stats.rating ?? 0} size="lg" />
          {stats.breakdown.length > 0 && (
            <div className="prof-stat-breakdown">
              {stats.breakdown.map(([source, rating]) => (
                <span key={source}>{SOURCE_LABELS[source] ?? source.toUpperCase()}: {rating.toFixed(2)}</span>
              ))}
            </div>
          )}
        </div>
        <div className="prof-stat-card">
          <span className="prof-stat-value">{stats.difficulty !== null ? <AnimatedNumber value={stats.difficulty} /> : '—'}</span>
          <span className="prof-stat-label">Difficulty</span>
          <div className="prof-difficulty-bar">
            <div className="prof-difficulty-fill" style={{
              width: `${((stats.difficulty ?? 0) / 5) * 100}%`,
              background: difficultyColor(stats.difficulty ?? 0),
            }} />
          </div>
        </div>
        <div className="prof-stat-card">
          <span className={`prof-stat-value ${summary.wouldTakeAgainPct !== null ? 'green' : ''}`}>
            {summary.wouldTakeAgainPct !== null ? <AnimatedNumber value={summary.wouldTakeAgainPct} decimals={0} suffix="%" /> : '—'}
          </span>
          <span className="prof-stat-label">Would Take Again</span>
          {!unfiltered && <span className="prof-stat-hint">All courses</span>}
        </div>
        {SHOW_SURVEY_STATS && (
          <div className="prof-stat-card">
            <span className="prof-stat-value">
              {summary.hoursPerWeek !== null ? <AnimatedNumber value={summary.hoursPerWeek} decimals={1} suffix="h" /> : '—'}
            </span>
            <span className="prof-stat-label">Hrs / Week</span>
          </div>
        )}
        <div className="prof-stat-card prof-stat-clickable" onClick={() => chartsRef.current?.scrollIntoView({ behavior: 'smooth' })}>
          <span className="prof-stat-value">{stats.numRatings ? stats.numRatings.toLocaleString() : '—'}</span>
          <span className="prof-stat-label">Total Ratings</span>
          <span className="prof-stat-hint">View distribution ↓</span>
        </div>
        {SHOW_SURVEY_STATS && (
          <div className="prof-stat-card prof-stat-clickable" onClick={() => reviewsRef.current?.scrollIntoView({ behavior: 'smooth' })}>
            <span className="prof-stat-value">{summary.numComments.toLocaleString()}</span>
            <span className="prof-stat-label">Total Comments</span>
            <span className="prof-stat-hint">Read reviews ↓</span>
          </div>
        )}
      </section>

      <div className="prof-hero-actions-row">
        <Link
          to={`/compare?a=${identity.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')}`}
          className="prof-compare-btn"
        >
          Compare
        </Link>
        {rmp.professorUrl && (
          <a href={rmp.professorUrl} target="_blank" rel="noreferrer" className="prof-rmp-btn">
            View on RMP →
          </a>
        )}
      </div>

      <section className="prof-section prof-charts-row" ref={chartsRef}>
        <div className="prof-chart-card">
          <h3 className="prof-chart-title">Rating Distribution</h3>
          <div className="prof-distribution">
            {ratingDistribution.map((d) => (
              <RatingBar key={d.star} star={d.star} count={d.count} max={maxCount} />
            ))}
          </div>
        </div>
        {gradeDistribution.length > 0 && (
          <div className="prof-chart-card" ref={gradesRef}>
            <h3 className="prof-chart-title">Grade Distribution</h3>
                  <div className="prof-grades">
                    {gradeDistribution.map((g) => (
                      <div key={g.grade} className="prof-grade-row">
                        <span className="prof-grade-label" style={{ color: g.color }}>{g.grade}</span>
                        <div className="prof-grade-track">
                          <div className="prof-grade-fill" style={{ width: gradesAnimated ? `${g.pct}%` : '0%', background: g.color }} />
                        </div>
                        <span className="prof-grade-count">{g.count}</span>
                      </div>
                    ))}
                  </div>
          </div>
        )}
      </section>

      {isImageModalOpen && identity.imageUrl && (
        <div className="prof-image-modal-overlay" onClick={() => setIsImageModalOpen(false)}>
          <div className="prof-image-modal" onClick={(e) => e.stopPropagation()}>
            <button
              className="prof-image-modal-close"
              onClick={() => setIsImageModalOpen(false)}
              aria-label="Close enlarged professor image"
            >
              ×
            </button>
            <img src={identity.imageUrl} alt={identity.name} className="prof-image-modal-img" />
          </div>
        </div>
      )}

      {courses.length > 0 && (
        <section className="prof-section">
          <div className="prof-section-header">
            <h2 className="prof-section-title">Courses Taught</h2>
            <div className="prof-section-actions">
              <button className="prof-action-link" onClick={() => setSelectedCourses(new Set(allCourseCodes))}>Select All</button>
              <button className="prof-action-link" onClick={() => setSelectedCourses(new Set())}>Clear All</button>
            </div>
          </div>
          <div className="prof-courses-compact">
            {courses.slice(0, COURSES_COLLAPSED_LIMIT).map(renderCourseRow)}
            {courses.length > COURSES_COLLAPSED_LIMIT && (
              <>
                <div className={`prof-courses-extra ${showAllCourses ? 'open' : ''}`}>
                  <div>{courses.slice(COURSES_COLLAPSED_LIMIT).map(renderCourseRow)}</div>
                </div>
                <button className="prof-courses-toggle" onClick={() => setShowAllCourses(v => !v)}>
                  {showAllCourses ? 'Show fewer' : `+${courses.length - COURSES_COLLAPSED_LIMIT} more courses`}
                  <svg className={`prof-courses-toggle-icon ${showAllCourses ? 'expanded' : ''}`} width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="6 9 12 15 18 9" />
                  </svg>
                </button>
              </>
            )}
          </div>
        </section>
      )}

      {showCourseTip && allCourseCodes.length > 0 && (
        <div className="prof-course-tip-wrapper">
          <div className="prof-course-tip">
            <div className="prof-course-tip-icon">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
            </div>
            <div className="prof-course-tip-body">
              <div className="prof-course-tip-label">Tip</div>
              <p className="prof-course-tip-text">
                To filter reviews by course, click <strong>Clear All</strong> in the Courses Taught section, then select the course you want to see reviews for.
              </p>
            </div>
            <button className="prof-course-tip-close" onClick={() => { localStorage.setItem('prof_course_tip_dismissed', '1'); setShowCourseTip(false); }} aria-label="Dismiss tip">
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
        </div>
      )}

      <section className="prof-section prof-reviews-section" ref={reviewsRef}>
        <div className="prof-reviews-header">
          <h2 className="prof-section-title">Reviews</h2>
          <div className="prof-review-tabs" ref={reviewTabsRef}>
            <div 
              className={`prof-review-pill-background ${isReviewPillReady ? 'animate' : ''}`} 
              style={{ 
                transform: `translateX(${reviewPillStyle.left}px)`, 
                width: `${reviewPillStyle.width}px`, 
                opacity: reviewPillStyle.opacity, 
                visibility: reviewPillStyle.opacity === 0 ? 'hidden' : 'visible' 
              }} 
            />
            <button className={`prof-review-tab ${reviewTab === 'rmp' ? 'active' : ''}`} onClick={() => setReviewTab('rmp')}>
              <span className="prof-review-tab-full">RateMyProfessor ({filteredRmpReviews.length})</span>
              <span className="prof-review-tab-short">RMP ({filteredRmpReviews.length})</span>
            </button>
            <button className={`prof-review-tab ${reviewTab === 'reddit' ? 'active' : ''}`} onClick={() => setReviewTab('reddit')}>
              <span className="prof-review-tab-full">Reddit ({redditMentions.length})</span>
              <span className="prof-review-tab-short">Reddit ({redditMentions.length})</span>
            </button>
          </div>
        </div>

        {reviewTab === 'rmp' && (
          <>
            <div className="prof-reviews-filters">
              <Dropdown className="feedback-dropdown" options={sortOptions} value={sortBy} onChange={setSortBy} placeholder="Sort by…" />
            </div>
            <div className="prof-reviews-list">
              {sortedReviews.length === 0 ? (
                <p className="prof-no-reviews">No reviews match current filters.</p>
              ) : (
                sortedReviews.slice(0, visibleReviews).map((r, i) => (
                  <div key={i} className={`prof-review-card ${isPinned(r.comment || '', pinSnippets.rmp) ? 'is-ask-pinned' : ''}`} style={{ borderLeftColor: r.quality >= 4 ? '#27ae60' : r.quality >= 3 ? '#f39c12' : '#e74c3c' }}>
                    {isPinned(r.comment || '', pinSnippets.rmp) && <span className="ask-pinned-label">From your question</span>}
                    <div className="prof-review-top">
                      <div className="prof-review-ratings">
                        <div className="prof-review-rating-item">
                          <span className="prof-review-rating-label">Quality</span>
                          <span className="prof-review-rating-value" data-score={String(r.quality)}>{r.quality}</span>
                        </div>
                        <div className="prof-review-rating-item">
                          <span className="prof-review-rating-label">Difficulty</span>
                          <span className="prof-review-rating-value" data-score={String(6 - r.difficulty)}>{r.difficulty}</span>
                        </div>
                      </div>
                      <div className="prof-review-meta">
                        <span className="prof-review-course">{courseCode(r.course)}</span>
                        <span className="prof-review-date">{formatReviewDate(r.date)}</span>
                      </div>
                    </div>
                    {r.comment && <p className="prof-review-comment">{r.comment}</p>}
                    <div className="prof-review-bottom">
                      {r.tags && (
                        <div className="prof-review-tags">
                          {r.tags.split('--').map(t => t.trim()).filter(Boolean).map((t, ti) => (
                            <span key={ti} className="prof-review-tag">{t}</span>
                          ))}
                        </div>
                      )}
                      <div className="prof-review-pills">
                        {r.grade && r.grade !== 'N/A' && <span className="prof-review-pill">Grade: {r.grade}</span>}
                        {r.attendance && r.attendance !== 'N/A' && <span className="prof-review-pill">Attendance: {r.attendance === 'true' || r.attendance === 'Mandatory' ? 'Mandatory' : 'Not Mandatory'}</span>}
                        {r.textbook && r.textbook !== 'N/A' && <span className="prof-review-pill">Textbook: {r.textbook === 'true' || r.textbook === 'Yes' ? 'Yes' : 'No'}</span>}
                        {r.online_class && r.online_class !== 'N/A' && <span className="prof-review-pill">{r.online_class === 'true' || r.online_class === 'Yes' ? 'Online' : 'In-Person'}</span>}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
            {visibleReviews < sortedReviews.length && (
              <button className="prof-load-more" onClick={() => setVisibleReviews(v => v + 10)}>
                Load More
              </button>
            )}
          </>
        )}

        {reviewTab === 'reddit' && (
          <>
            <div className="prof-reddit-controls">
              <div className="reddit-search-container">
                <input
                  type="text"
                  className="reddit-search-input"
                  placeholder="Search Reddit mentions..."
                  value={redditSearch}
                  onChange={e => { setRedditSearch(e.target.value); setVisibleRedditMentions(10); }}
                />
              </div>
              <Dropdown className="reddit-sort-dropdown" options={redditSentimentOptions} value={redditSentiment} onChange={(v) => { setRedditSentiment(v); setVisibleRedditMentions(10); }} />
            </div>
            <div className="prof-reddit-list">
              {filteredRedditMentions.length === 0 ? (
                <p className="prof-no-reviews">No Reddit mentions found for this professor.</p>
              ) : (
                filteredRedditMentions.slice(0, visibleRedditMentions).map((m, i) => {
                  const redditUrl = safeRedditUrl(m.permalink);
                  const dateStr = formatRedditDate(m.created_utc);
                  const sScore = m.sentiment_score ?? 0;
                  // Clamp the pointer so the label/arrow never clip the card edge at extreme scores.
                  const markerPct = Math.min(90, Math.max(10, (sScore + 1) / 2 * 100));
                  const magnitudePct = Math.round(Math.abs(sScore) * 100);
                  const word = m.sentiment ? m.sentiment.charAt(0).toUpperCase() + m.sentiment.slice(1) : 'Neutral';
                  const label = `${word} (${magnitudePct}%)`;
                  return (
                  <div key={i} className={`reddit-comment-bubble ${isPinned(m.body || '', pinSnippets.reddit) ? 'is-ask-pinned' : ''}`}>
                    {isPinned(m.body || '', pinSnippets.reddit) && <span className="ask-pinned-label">From your question</span>}
                    <div className="reddit-comment-meta">
                      {dateStr && <span className="reddit-comment-date">{dateStr}</span>}
                      <div className="reddit-comment-actions">
                        {m.score != null && <span className="reddit-comment-score">▲ {m.score}</span>}
                        {redditUrl && <a className="reddit-comment-link" href={redditUrl} target="_blank" rel="noopener noreferrer">View on Reddit ↗</a>}
                      </div>
                    </div>
                    <p className="reddit-comment-body">{m.body}</p>
                    <div className="reddit-sentiment">
                      <div className="reddit-sentiment-pointer" style={{ left: `${markerPct}%` }}>
                        <span className="reddit-sentiment-label" style={{ color: sentimentBorderColor(m.sentiment) }}>{label}</span>
                        <span className="reddit-sentiment-arrow" style={{ color: sentimentBorderColor(m.sentiment) }}>▼</span>
                      </div>
                      <div className="reddit-sentiment-track" />
                    </div>
                  </div>
                  );
                })
              )}
            </div>
            {visibleRedditMentions < filteredRedditMentions.length && (
              <button className="prof-load-more" onClick={() => setVisibleRedditMentions(v => v + 10)}>
                Load More
              </button>
            )}
          </>
        )}
      </section>

      <Footer />
      <button
        className={`prof-back-to-top ${showBackToTop ? 'visible' : ''}`} 
        onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })} 
        aria-label="Back to top"
      >
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="18 15 12 9 6 15" />
        </svg>
      </button>
    </div>
  );
};

export default Professor;
