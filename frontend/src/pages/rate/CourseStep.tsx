import { useEffect, useState } from 'react';
import { fetchCourseSuggestions, fetchSearchSuggestions } from '../../api/api';
import { useDebouncedValue } from '../../utils/useDebouncedValue';
import { ChoiceGroup, StepFoot } from './ChoiceGroup';
import type { ChoiceOption } from './ChoiceGroup';
import { formatCode, lastName, ownMatches } from './rateFlow';
import type { RateCourse, RateProfessor } from './rateFlow';

const OTHER = '+other';

interface CourseStepProps {
  professor: RateProfessor;
  fresh: RateCourse[];
  rated: RateCourse[];
  // Some of the professor's courses aren't tiles, so search finds them.
  more: boolean;
  // The courses are newest-first, so the tiles are the most recent ones.
  recent: boolean;
  selected?: string;
  onPick: (c: RateCourse) => void;
  onOther: () => void;
}

export function Pencil() {
  return (
    <span className="rate-pencil" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 20h9" />
        <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
      </svg>
    </span>
  );
}

// One label for a course tile and a search result, so both read the same aloud.
const courseAria = (c: RateCourse, isRated: boolean) =>
  `${formatCode(c.code)}${c.name ? `, ${c.name}` : ''}${isRated ? ', update your rating' : ''}`;

export function CourseStep({ professor, fresh, rated, more, recent, selected, onPick, onOther }: CourseStepProps) {
  const option = (c: RateCourse, isRated: boolean): ChoiceOption<string> => ({
    value: c.code,
    aria: courseAria(c, isRated),
    className: isRated ? 'course rated' : 'course',
    label: (
      <>
        <span className="rate-cmain"><b>{formatCode(c.code)}</b>{c.name && <span className="rate-cname">{c.name}</span>}</span>
        {isRated && <Pencil />}
      </>
    ),
  });
  const options = fresh.map((c) => option(c, false));
  const otherLabel = more ? 'Search for another course' : 'A different course';
  options.push({ value: OTHER, aria: otherLabel, label: `+ ${otherLabel}`, className: 'course dash' });
  const ratedOptions = rated.map((c) => option(c, true));
  if (ratedOptions.length) ratedOptions[0].heading = 'Already rated';
  options.push(...ratedOptions);

  return (
    <ChoiceGroup
      legend="Which course?"
      subtitle={more
        ? `Prof. ${lastName(professor.name)}'s most ${recent ? 'recent' : 'rated'} courses.`
        : `Courses we know Prof. ${lastName(professor.name)} has taught.`}
      options={options}
      value={selected}
      layout="stack"
      onPick={(v) => (v === OTHER ? onOther() : onPick([...fresh, ...rated].find((c) => c.code === v)!))}
    />
  );
}

const NEW_CODE = /^[A-Z]{2,5}\d{4}[A-Z]?$/;
// The catalog search only matches a code written without a space ("cs1800", not "CS 1800").
const CODE_LIKE = /^[A-Za-z]{2,5}\s*\d{1,4}[A-Za-z]?$/;

interface OtherCourseStepProps {
  own: RateCourse[];
  rated: string[];
  slug: string | null;
  onPick: (c: RateCourse) => void;
  onBack: () => void;
}

export function OtherCourseStep({ own, rated, slug, onPick, onBack }: OtherCourseStepProps) {
  const [query, setQuery] = useState('');
  const [newName, setNewName] = useState('');
  const typed = query.trim();
  const term = CODE_LIKE.test(typed) ? typed.replace(/\s+/g, '') : typed;
  const debounced = useDebouncedValue(term, 200);
  const [found, setFound] = useState<{ q: string; items: RateCourse[] } | null>(null);

  useEffect(() => {
    if (debounced.length < 2) return;
    let cancelled = false;
    fetchSearchSuggestions(debounced, 'Course')
      .then((rows) => {
        if (cancelled) return;
        const items = rows.flatMap((r) => (r.type === 'course' ? [{ code: r.code, name: r.name, isNew: false, terms: [] }] : []));
        setFound({ q: debounced, items: items.slice(0, 5) });
      })
      .catch(() => { /* leave the previous results */ });
    return () => { cancelled = true; };
  }, [debounced]);

  // The professor's own matches lead, since the catalog search misses Banner-only codes.
  const mine = ownMatches(own, term);
  const catalog = found !== null && found.q === term ? found.items : null;
  const settled = catalog === null && mine.length === 0
    ? null
    : [...mine, ...(catalog ?? []).filter((c) => !mine.some((m) => m.code === c.code))].slice(0, 5);
  const code = typed.replace(/\s+/g, '').toUpperCase();
  const canAdd = settled !== null && settled.length === 0 && NEW_CODE.test(code);
  // canAdd waits on the catalog search for the debounced term, so this needs no debounce of its own.
  const addCode = canAdd ? code : '';
  const [nearby, setNearby] = useState<{ q: string; items: RateCourse[] } | null>(null);

  useEffect(() => {
    if (!addCode) return;
    let cancelled = false;
    fetchCourseSuggestions(addCode, slug).then((rows) => {
      if (!cancelled) setNearby({ q: addCode, items: rows.map((r) => ({ code: r.code, name: r.name ?? '', isNew: false, terms: [] })) });
    });
    return () => { cancelled = true; };
  }, [addCode, slug]);

  const answered = canAdd && nearby !== null && nearby.q === code;
  // A Banner-only code typed exactly is a pick like any search result, not a new course.
  const exact = answered ? nearby.items.find((c) => c.code === code) : undefined;
  const suggestions = answered && !exact ? nearby.items : [];
  const adding = answered && !exact;

  const courseButton = (c: RateCourse) => {
    const isRated = rated.includes(c.code);
    return (
      <button
        key={c.code}
        type="button"
        className={`rate-sugg${isRated ? ' rated' : ''}`}
        aria-label={isRated ? courseAria(c, true) : undefined}
        onClick={() => onPick(c)}
      >
        <span>
          <b>{formatCode(c.code)}</b>
          {c.name && <small>{c.name}</small>}
        </span>
        {isRated && <Pencil />}
      </button>
    );
  };

  return (
    <>
      <h1 className="rate-q" tabIndex={-1}>Which course?</h1>
      <p className="rate-sub">Search every course, or add one we don't have.</p>
      <div className="rate-field">
        <label htmlFor="rate-course-search">Search all courses</label>
        <input
          id="rate-course-search"
          className="rate-input"
          autoComplete="off"
          placeholder="e.g. CS 2500"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      {settled && settled.length > 0 && (
        <div className="rate-suggs">{settled.map(courseButton)}</div>
      )}
      {exact && <div className="rate-suggs">{courseButton(exact)}</div>}
      {suggestions.length > 0 && (
        <>
          <p className="rate-hint rate-note">Did you mean one of these?</p>
          <div className="rate-suggs">{suggestions.map(courseButton)}</div>
        </>
      )}
      {adding && (
        <>
          <p className="rate-hint rate-note">
            {suggestions.length > 0
              ? `Or keep ${formatCode(code)}: name it and it's added with your rating.`
              : `${formatCode(code)} isn't in our catalog yet. Name it and it's added with your rating.`}
          </p>
          <div className="rate-field">
            <label htmlFor="rate-course-name">Course name</label>
            <input
              id="rate-course-name"
              className="rate-input"
              autoComplete="off"
              placeholder="e.g. Topics: Applied ML"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
          </div>
        </>
      )}
      {settled && settled.length === 0 && !NEW_CODE.test(code) && (
        <p className="rate-hint rate-note" role="status">No courses match. Type the full code, like CS 4999, to add a new one.</p>
      )}
      <StepFoot onBack={onBack}>
        {adding && (
          <button
            type="button"
            className="rate-btn"
            disabled={!newName.trim()}
            onClick={() => onPick({ code, name: newName.trim(), isNew: true, terms: [] })}
          >
            Continue
          </button>
        )}
      </StepFoot>
    </>
  );
}
