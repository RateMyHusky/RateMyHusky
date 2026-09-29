import { useState, useEffect, useRef, useMemo } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import Dropdown from './Dropdown';
import { fetchSearchSuggestions, askChat } from '../api/api';
import type { SearchSuggestion, ChatResponse } from '../api/api';
import { saveAskSession, loadAskSession, clearAskSession } from '../utils/askSession';
import { ASK_ENABLED } from '../config';
import './SearchBar.css';

// Navigation state a clicked citation carries so the destination breadcrumb reads "← Ask" and
// clicking it lands back on the homepage with the Ask box re-hydrated from sessionStorage.
const ASK_FROM_STATE = { fromPage: { label: 'Ask', url: '/' }, restoreAsk: true } as const;

const SOURCE_LABEL: Record<string, string> = {
  reddit: "Reddit",
  rmp: "RateMyProfessor",
  trace: "Student Reviews",
};

const searchOptions = [
  { value: 'Professor', label: 'Professor' },
  { value: 'Course', label: 'Course' },
  { value: 'Ask', label: 'Ask' },
].filter((o) => ASK_ENABLED || o.value !== 'Ask');

interface SearchBarProps {
  // Bump this (e.g. Date.now()) to force the bar into Ask mode and focus it.
  forceAsk?: number;
  // True when the homepage was reached via the "← Ask" breadcrumb: re-hydrate the last Ask
  // question/answer from sessionStorage instead of starting blank. Any other homepage load
  // (logo click, refresh, direct visit) leaves this false and clears the stored session.
  restoreAsk?: boolean;
}

const SearchBar = ({ forceAsk, restoreAsk }: SearchBarProps) => {
  const navigate = useNavigate();
  const location = useLocation();
  // On mount only: restore the saved Ask session when arriving via the "← Ask" breadcrumb,
  // otherwise drop any stale session so a plain homepage load starts blank. Guarded to run once
  // so it never re-clears a session that a later ask has just saved (this runs every render).
  const restored = useRef(ASK_ENABLED && restoreAsk ? loadAskSession() : null);
  const didInit = useRef(false);
  if (!didInit.current) {
    didInit.current = true;
    if (!restoreAsk || !ASK_ENABLED) clearAskSession();
  }
  const [searchType, setSearchType] = useState(restored.current ? 'Ask' : 'Professor');
  const [query, setQuery] = useState(restored.current?.query ?? '');
  const [suggestions, setSuggestions] = useState<SearchSuggestion[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(!!restored.current);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [isFocused, setIsFocused] = useState(false);
  const [placeholder, setPlaceholder] = useState('');
  const [askLoading, setAskLoading] = useState(false);
  const [askResult, setAskResult] = useState<ChatResponse | null>(restored.current?.result ?? null);
  const [askedAt, setAskedAt] = useState<number>(restored.current?.askedAt ?? 0);

  const isAsk = searchType === 'Ask';

  // The restoreAsk flag lives in history state, which the browser replays on refresh. Scrub it
  // once after restoring so a refresh sees a plain load (clears the session) — meeting "answer
  // only persists across a breadcrumb-back, not a refresh". Runs after mount, restore already done.
  useEffect(() => {
    if (restoreAsk) {
      const { restoreAsk: _drop, ...rest } = (location.state ?? {}) as Record<string, unknown>;
      void _drop;
      navigate('.', { replace: true, state: Object.keys(rest).length ? rest : undefined });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const wrapperRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Guards for submitAsk's post-await effects: reqId invalidates a stale response when the
  // search type changes mid-request (Issue 8); mounted prevents state/dispatch after unmount
  // (Issue 21). Both are checked on the same line right after the await.
  const askReqSeq = useRef(0);
  const mounted = useRef(true);
  useEffect(() => () => { mounted.current = false; }, []);

  // "Try Now" (home ask bubble) switches the bar into Ask mode and focuses it.
  useEffect(() => {
    if (forceAsk === undefined || !ASK_ENABLED) return;
    setSearchType('Ask');
    inputRef.current?.focus();
  }, [forceAsk]);

  const professorExamples = useMemo(() => [
    "Alan Mislove", "Ravi Sundaram", "Dan Felushko", "Cristina Nita-Rotaru",
    "Stacy Marsella", "Kathleen Durant", "Gene Cooperman", "Amit Shesh",
    "Mark Sheldon", "Nat Tuck", "Abhi Shelat", "Bryan Lackaye",
    "Predrag Radivojac", "Martin Schedlbauer", "Laney Strange",
    "Ben Hescott", "Rajmohan Rajaraman", "Keith Bagley",
    "Jonathan Meil", "Robert Platt", "Amal Ahmed", "Karl Lieberherr",
    "Frank Tip", "Jay McCarthy", "Christo Wilson",
    "Sami Rollins", "David Choffnes", "John Rachlin",
    "Alina Ene", "Pete Hartman", "Rose Yu", "Ji-Yong Shin",
    "Jonathan Ullman", "Stavros Tripakis", "Byron Wallace"
  ], []);

  const courseExamples = useMemo(() => [
    "CS 2500", "CS 3500", "CS 4500", "ECON 1115", "MATH 1341",
    "CY 2550", "PHYS 1161", "ACCT 1201", "MKTG 2101", "BIOL 1111",
    "CS 1800", "CS 2510", "CS 3000", "CS 3200", "CS 3650",
    "CS 3700", "CS 3800", "CS 4400", "CS 4530", "CS 4550",
    "ENGW 1111", "ENGW 3302", "MATH 1342", "MATH 2331", "MATH 3081",
    "PHYS 1151", "PHYS 1155", "CHEM 1161", "PSYC 1101", "HIST 1130",
    "EECE 2160", "EECE 2322", "DS 2000", "DS 2001", "DS 3000",
    "ARTF 1122", "MUSC 1201", "PHIL 1101", "ENVR 1101", "FINA 2201"
  ], []);

  const askExamples = useMemo(() => [
    // single professor / course
    "Is Guha hard?",
    "How are Mislove's lectures?",
    "Does Abhi Shelat give hard exams?",
    "Is Rachlin an easy grader?",
    "Is CS 3000 worth taking?",
    "How tough is Discrete Structures?",
    "Is Schedlbauer a good teacher?",
    "When should I take ENGW3302?",
    "Should I take Theory of Computation?",
    "Is Operating Systems brutal?",
    "Is Software Engineering project-heavy?",
    // comparisons (two entities)
    "Mislove or Rachlin for CS 2500?",
    "Is CS 3500 harder than CS 3000?",
    "Shesh vs Cooperman — who's better?",
    "Should I take CS 3650 or CS 3700 first?",
    "Lieberherr or Tip for software engineering?",
    "Is MATH 1341 or MATH 1342 more work?",
    "Nita-Rotaru vs Choffnes for Networks?",
    // multi-entity / both at once
    "Are CS 2500 and CS 2510 a big jump?",
    "Compare the CS 2100's Professors",
    // stats-targeting
    "What's Mislove's average rating?",
    "What's the difficulty score for CS 3000?",
    "What percent would take Abhi Shelat again?",
    "Which CS course has the highest rating?",
    "Is CS 3200's workload above average?",
    "What's Elena Strange's would-take-again percentage?",
    // comments-targeting
    "What do students say about Chieh Wu?",
    "What are the reviews like for CS 3650?",
    "Are there reviews about CS 2510's workload?",
    "What do students think of Schedlbauer's lectures?"
  ], []);

  // Typing animation logic
  useEffect(() => {
    if (isFocused || query) {
      setPlaceholder(
        isAsk ? 'Ask about a professor or course...'
        : searchType === 'Professor' ? 'Search by professor name...'
        : 'Search by course name or code...'
      );
      return;
    }

    const examples = isAsk ? askExamples : searchType === 'Professor' ? professorExamples : courseExamples;
    let currentExampleIndex = Math.floor(Math.random() * examples.length);
    let currentText = "";
    let isDeleting = false;
    let typingSpeed = 100;

    const type = () => {
      const fullText = examples[currentExampleIndex];

      if (isDeleting) {
        currentText = fullText.substring(0, currentText.length - 1);
        typingSpeed = 50;
      } else {
        currentText = fullText.substring(0, currentText.length + 1);
        typingSpeed = 100;
      }

      setPlaceholder(isAsk ? currentText : `Search for "${currentText}"`);

      if (!isDeleting && currentText === fullText) {
        isDeleting = true;
        typingSpeed = 2000; // Pause at end
      } else if (isDeleting && currentText === "") {
        isDeleting = false;
        currentExampleIndex = (currentExampleIndex + 1) % examples.length;
        typingSpeed = 500; // Pause before next
      }

      timeoutId = setTimeout(type, typingSpeed);
    };

    let timeoutId = setTimeout(type, typingSpeed);
    return () => clearTimeout(timeoutId);
  }, [isFocused, query, searchType, isAsk, professorExamples, courseExamples, askExamples]);

  const handleSearchTypeChange = (newType: string) => {
    askReqSeq.current++; // invalidate any in-flight Ask request
    setSearchType(newType);
    setQuery('');
    setSuggestions([]);
    setShowSuggestions(false);
    setAskResult(null);
    setAskLoading(false);
  };

  // Debounced fetch (search modes only — Ask costs LLM tokens, so it never fetches as-you-type)
  useEffect(() => {
    if (isAsk) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);

    const trimmedQuery = query.trim();
    if (trimmedQuery.length < 2) {
      // Don't call setState here if it's already empty/false
      // But we need to handle it. Actually, the lint error is specific to SYNC calls in body.
      // We can use an async or just handle it.
      return;
    }

    debounceRef.current = setTimeout(async () => {
      try {
        const results = await fetchSearchSuggestions(trimmedQuery, searchType);
        const limitedResults = searchType === 'Professor' ? results.slice(0, 3) : results;
        setSuggestions(limitedResults);
        setShowSuggestions(limitedResults.length > 0);
        setActiveIndex(-1);
      } catch {
        setSuggestions([]);
        setShowSuggestions(false);
      }
    }, 200);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, searchType, isAsk]);

  // Handle query change to sync suggestions state
  const handleQueryChange = (val: string) => {
    setQuery(val);
    if (val.trim().length < 2) {
      setSuggestions([]);
      setShowSuggestions(false);
    }
  };

  // Ask submit: one self-contained question → one answer (single-shot, no history).
  const submitAsk = async () => {
    const q = query.trim();
    if (q.length < 2 || askLoading) return;
    const reqId = ++askReqSeq.current;
    setAskResult(null);
    setAskLoading(true);
    setShowSuggestions(true);
    const { status, body } = await askChat(q);
    const now = Date.now();
    if (reqId !== askReqSeq.current || !mounted.current) return;
    setAskLoading(false);
    setAskResult(body);
    setAskedAt(now);
    // Persist so a clicked citation can return here via the "← Ask" breadcrumb.
    saveAskSession(q, body, now);
    if (status === 401) {
      // No sign-in modal lives here; mirror the navbar's open-feedback event pattern.
      window.dispatchEvent(new CustomEvent('open-signin'));
    }
  };

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setShowSuggestions(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // Removed redundant clear effect

  const handleSelect = (suggestion: SearchSuggestion) => {
    setShowSuggestions(false);
    const fromCatalog = location.pathname === '/professors'
      ? `${location.pathname}${location.search}`
      : undefined;
    if (suggestion.type === 'professor') {
      const slug = suggestion.slug;
      navigate(`/professors/${slug}`, { state: { fromCatalog } });
    } else {
      const code = suggestion.code.toLowerCase();
      navigate(`/courses/${code}`);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (isAsk) {
      if (e.key === 'Enter') {
        e.preventDefault();
        submitAsk();
      } else if (e.key === 'Escape') {
        setShowSuggestions(false);
      }
      return;
    }
    if (!showSuggestions || suggestions.length === 0) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((prev) => {
        const next = prev < suggestions.length - 1 ? prev + 1 : 0;
        document.querySelector(`.suggestion-item:nth-child(${next + 1})`)?.scrollIntoView({ block: 'nearest' });
        return next;
      });
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((prev) => {
        const next = prev > 0 ? prev - 1 : suggestions.length - 1;
        document.querySelector(`.suggestion-item:nth-child(${next + 1})`)?.scrollIntoView({ block: 'nearest' });
        return next;
      });
    } else if (e.key === 'Enter' && activeIndex >= 0) {
      e.preventDefault();
      handleSelect(suggestions[activeIndex]);
    } else if (e.key === 'Escape') {
      setShowSuggestions(false);
    }
  };

  return (
    <div className="search-wrapper" ref={wrapperRef}>
      <div className="search-bar">
        <div onMouseDown={() => setShowSuggestions(false)}>
          <Dropdown
            className="search-dropdown"
            options={searchOptions}
            value={searchType}
            onChange={handleSearchTypeChange}
          />
        </div>

        <div className="search-divider" />

        <span className="search-icon">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
        </span>

        <input
          ref={inputRef}
          className="search-input"
          type="text"
          placeholder={placeholder}
          value={query}
          onChange={(e) => handleQueryChange(e.target.value)}
          onFocus={() => {
            setIsFocused(true);
            if (isAsk ? (askResult || askLoading) : suggestions.length > 0) setShowSuggestions(true);
          }}
          onBlur={() => setIsFocused(false)}
          onKeyDown={handleKeyDown}
        />
      </div>

      {showSuggestions && !isAsk && (
        <ul className="search-suggestions">
          {suggestions.map((s, i) => (
            <li
              key={s.type === 'professor' ? s.name : s.code}
              className={`suggestion-item ${i === activeIndex ? 'active' : ''}`}
              onClick={() => handleSelect(s)}
              onMouseEnter={() => setActiveIndex(i)}
            >
              {s.type === 'professor' ? (
                <>
                  <div className="suggestion-main">
                    <span className="suggestion-name">{s.name}</span>
                    <span className="suggestion-dept">{s.dept}</span>
                  </div>
                  {s.rating !== null && (
                    <span className="suggestion-rating">{s.rating.toFixed(2)}</span>
                  )}
                </>
              ) : (
                <div className="suggestion-main">
                  <span className="suggestion-name">
                    <span className="suggestion-code">{s.code}</span>
                    {' '}{s.name}
                  </span>
                  <span className="suggestion-dept">{s.dept}</span>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {showSuggestions && isAsk && (askLoading || askResult) && (
        <div className="ask-result">
          {askLoading ? (
            <p className="ask-thinking">
              Thinking<span className="ask-thinking-dots"><span>.</span><span>.</span><span>.</span></span>
            </p>
          ) : askResult ? (
            <AskResult result={askResult} askedAt={askedAt} />
          ) : null}
        </div>
      )}
    </div>
  );
};

function AskResult({ result, askedAt }: { result: ChatResponse; askedAt: number }) {
  if (result.mode === 'question') {
    // Fallback entity (used when a source has no per-source tag, e.g. old cached answers).
    const fallbackHref = result.course_code
      ? `/courses/${result.course_code.toLowerCase()}`
      : result.professor_slug
      ? `/professors/${result.professor_slug}`
      : null;
    // Show a source only if it's actually cited. Prefer the backend's validated `cited` list
    // (handles grouped citations like [1, 2]); fall back to the substring probe for older
    // cached payloads that predate the field.
    const sources = result.sources ?? [];
    const cited = Array.isArray(result.cited)
      ? sources.filter((s) => result.cited!.includes(s.source_id))
      : sources.filter((s) => result.answer.includes(`[${s.source_id}]`));
    return (
      <>
        <p className="ask-answer">{result.answer}</p>
        {cited.length > 0 && (
          <ol className="ask-sources">
            {cited.map((s) => {
              // Course citations win the course link (courses page has no pin behavior yet).
              const courseHref = s.course_code ? `/courses/${s.course_code.toLowerCase()}` : null;
              const profHref = s.professor_slug ? `/professors/${s.professor_slug}` : null;
              const href = courseHref ?? profHref ?? fallbackHref;
              // Pins only travel to professor pages, and only for citations whose destination
              // is a professor (no course_code). Carry every cited source sharing this slug.
              const pinToProfessor = !s.course_code && !!s.professor_slug;
              const sourcesForEntity = pinToProfessor
                ? cited
                    .filter((o) => !o.course_code && o.professor_slug === s.professor_slug)
                    .map((o) => ({ source: o.source ?? null, snippet: o.snippet }))
                : [];
              const linkProps = pinToProfessor
                ? {
                    state: {
                      ...ASK_FROM_STATE,
                      askPins: {
                        askedAt,
                        clicked: { source: s.source ?? null, snippet: s.snippet },
                        sources: sourcesForEntity,
                      },
                    },
                  }
                : { state: ASK_FROM_STATE };
              return (
                <li key={s.source_id}>
                  {href ? (
                    <Link className="ask-source-link" to={href} {...linkProps}>[{s.source_id}]</Link>
                  ) : (
                    <span className="ask-source-link">[{s.source_id}]</span>
                  )}
                  <span className="ask-source-badge">{SOURCE_LABEL[s.source ?? ''] ?? 'Reddit'}</span>
                  <span className="ask-source-snippet">{s.snippet}</span>
                </li>
              );
            })}
          </ol>
        )}
        <p className="ask-disclaimer">{result.disclaimer}</p>
      </>
    );
  }

  if (result.mode === 'disambiguation') {
    return <p className="ask-answer">{result.message}</p>;
  }

  if (result.mode === 'error') {
    return <p className="ask-answer">{result.message}</p>;
  }

  if (result.mode === 'course_list') {
    return (
      <>
        <p className="ask-answer">{result.answer}</p>
        {result.courses.length > 0 && (
          <ol className="ask-sources">
            {result.courses.map((c) => (
              <li key={c.code}>
                <Link className="ask-source-link" to={`/courses/${c.code.toLowerCase()}`} state={ASK_FROM_STATE}>{c.code}</Link>
                <span className="ask-source-snippet">
                  {c.name}{c.rating != null ? ` · ${c.rating.toFixed(1)}★` : ''}
                </span>
              </li>
            ))}
          </ol>
        )}
        <p className="ask-disclaimer">{result.disclaimer}</p>
      </>
    );
  }

  // out_of_scope | thin_data | keyword — banner/message + any keyword comments
  type KeywordComment = {
    snippet?: string;
    link?: { type: 'professor' | 'course'; value: string } | null;
  };
  const keywordComments = (result.comments ?? []).slice(0, 10) as KeywordComment[];
  return (
    <>
      {(result.banner || result.message) && (
        <p className="ask-answer">{result.banner || result.message}</p>
      )}
      {keywordComments.length > 0 && (
        <ol className="ask-sources">
          {keywordComments.map((com, i) => {
            // [N] citation links to the matched professor/course profile; plain when none.
            const href = com.link
              ? com.link.type === 'course'
                ? `/courses/${com.link.value.toLowerCase()}`
                : `/professors/${com.link.value}`
              : null;
            // Keyword comments are Reddit-sourced. For a professor link, carry every visible
            // comment pinned to the same professor so the Professor page can hoist + highlight
            // them (same shape the LLM path sends); the clicked one drives the scroll.
            const pinToProfessor = com.link?.type === 'professor';
            const sourcesForEntity = pinToProfessor
              ? keywordComments
                  .filter((o) => o.link?.type === 'professor' && o.link.value === com.link!.value)
                  .map((o) => ({ source: 'reddit' as const, snippet: o.snippet ?? '' }))
              : [];
            const linkState = pinToProfessor
              ? {
                  ...ASK_FROM_STATE,
                  askPins: {
                    askedAt,
                    clicked: { source: 'reddit' as const, snippet: com.snippet ?? '' },
                    sources: sourcesForEntity,
                  },
                }
              : ASK_FROM_STATE;
            const marker = `[${i + 1}]`;
            return (
              <li key={i}>
                {href ? (
                  <Link className="ask-source-link" to={href} state={linkState}>{marker}</Link>
                ) : (
                  <span className="ask-source-link">{marker}</span>
                )}
                <span className="ask-source-snippet">{com.snippet}</span>
              </li>
            );
          })}
        </ol>
      )}
    </>
  );
}

export default SearchBar;