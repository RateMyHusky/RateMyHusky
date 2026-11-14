import { useState, useEffect, useRef, useMemo } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import Dropdown from './Dropdown';
import { fetchSearchSuggestions } from '../api/api';
import type { SearchSuggestion } from '../api/api';
import { useTypingPlaceholder } from '../hooks/useTypingPlaceholder';
import './SearchBar.css';

// A course code as a student types it: "cs2500", "CS 2500", "math 1341".
const COURSE_CODE = /^[a-z]{2,5}\s*\d{4}[a-z]?$/i;
const searchOptions = [
  { value: 'Professor', label: 'Professor' },
  { value: 'Course', label: 'Course' },
];

const SearchBar = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchType, setSearchType] = useState('Professor');
  const [query, setQuery] = useState('');
  const [suggestions, setSuggestions] = useState<SearchSuggestion[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [isFocused, setIsFocused] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
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

  const placeholder = useTypingPlaceholder(
    searchType === 'Professor' ? professorExamples : courseExamples,
    searchType === 'Professor' ? 'Search by professor name...' : 'Search by course name or code...',
    isFocused || !!query,
  );

  const handleSearchTypeChange = (newType: string) => {
    setSearchType(newType);
    setQuery('');
    setSuggestions([]);
    setShowSuggestions(false);
  };

  // Debounced fetch of search suggestions
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);

    const trimmedQuery = query.trim();
    if (trimmedQuery.length < 2) {
      // Don't call setState here if it's already empty/false
      // But we need to handle it. Actually, the lint error is specific to SYNC calls in body.
      // We can use an async or just handle it.
      return;
    }

    // Set when the query or type changes, so a response that lands after the box was cleared
    // or retyped can't reopen the dropdown.
    let stale = false;
    debounceRef.current = setTimeout(async () => {
      try {
        const results = await fetchSearchSuggestions(trimmedQuery, searchType);
        if (stale) return;
        const limitedResults = searchType === 'Professor' ? results.slice(0, 3) : results;
        setSuggestions(limitedResults);
        // Open even with no matches: the "See all results" row is always there.
        setShowSuggestions(true);
        setActiveIndex(-1);
      } catch {
        if (stale) return;
        setSuggestions([]);
        setShowSuggestions(false);
      }
    }, 200);

    return () => {
      stale = true;
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, searchType]);

  // Handle query change to sync suggestions state
  const handleQueryChange = (val: string) => {
    setQuery(val);
    if (val.trim().length < 2) {
      setSuggestions([]);
      setShowSuggestions(false);
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

  // Where Enter and the dropdown's last row go: the catalog for the current mode, filtered by
  // the query. A course code ("cs 2500") is never a professor's name, so it opens the course
  // catalog from either mode.
  const trimmedQuery = query.trim();
  const codeInProfessorMode = searchType === 'Professor' && COURSE_CODE.test(trimmedQuery);
  const catalogHref = `${searchType === 'Course' || codeInProfessorMode ? '/courses' : '/professors'}?q=${encodeURIComponent(trimmedQuery)}`;
  const openCatalog = () => {
    setShowSuggestions(false);
    navigate(catalogHref);
  };
  // The "See all results" row sits after the suggestions, at index suggestions.length.
  const rowCount = suggestions.length + 1;

  const handleKeyDown = (e: React.KeyboardEvent) => {
    // The Enter that commits a Chinese, Japanese or Korean IME composition isn't a submit.
    if (e.nativeEvent.isComposing) return;
    // Enter with no suggestion highlighted opens the catalog, so a search with no suggestions
    // (or one the student didn't arrow into) still goes somewhere.
    const highlighted = showSuggestions && activeIndex >= 0 ? suggestions[activeIndex] : undefined;
    if (e.key === 'Enter' && !highlighted) {
      if (!trimmedQuery) return;
      e.preventDefault();
      openCatalog();
      return;
    }
    if (!showSuggestions) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((prev) => {
        const next = prev < rowCount - 1 ? prev + 1 : 0;
        document.querySelector(`.suggestion-item:nth-child(${next + 1})`)?.scrollIntoView({ block: 'nearest' });
        return next;
      });
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((prev) => {
        const next = prev > 0 ? prev - 1 : rowCount - 1;
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
            ariaLabel="Search type"
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
          aria-label={searchType === 'Professor' ? 'Search professors' : 'Search courses'}
          type="text"
          placeholder={placeholder}
          value={query}
          onChange={(e) => handleQueryChange(e.target.value)}
          onFocus={() => {
            setIsFocused(true);
            if (suggestions.length > 0) setShowSuggestions(true);
          }}
          onBlur={() => setIsFocused(false)}
          onKeyDown={handleKeyDown}
        />
      </div>

      {showSuggestions && (
        <ul className="search-suggestions">
          {suggestions.map((s, i) => (
            <li
              key={s.type === 'professor' ? s.slug : s.code}
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
          <li
            className={`suggestion-item suggestion-see-all ${activeIndex === suggestions.length ? 'active' : ''}`}
            onClick={openCatalog}
            onMouseEnter={() => setActiveIndex(suggestions.length)}
          >
            {codeInProfessorMode
              ? <>Search courses for “{trimmedQuery.toUpperCase()}” →</>
              : suggestions.length === 0
                ? <>No quick matches. Search all {searchType === 'Course' ? 'courses' : 'professors'} for “{trimmedQuery}” →</>
                : <>See all results for “{trimmedQuery}” →</>}
          </li>
        </ul>
      )}

    </div>
  );
};

export default SearchBar;
