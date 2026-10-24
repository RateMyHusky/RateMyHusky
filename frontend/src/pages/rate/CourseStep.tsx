import { useEffect, useState } from 'react';
import { fetchSearchSuggestions } from '../../api/api';
import { useDebouncedValue } from '../../utils/useDebouncedValue';
import { ChoiceGroup, StepFoot } from './ChoiceGroup';
import type { ChoiceOption } from './ChoiceGroup';
import { formatCode, lastName } from './rateFlow';
import type { RateCourse, RateProfessor } from './rateFlow';

const OTHER = '+other';

interface CourseStepProps {
  professor: RateProfessor;
  fresh: RateCourse[];
  rated: RateCourse[];
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

export function CourseStep({ professor, fresh, rated, selected, onPick, onOther }: CourseStepProps) {
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
  options.push({ value: OTHER, aria: 'A different course', label: '+ A different course', className: 'course dash' });
  const ratedOptions = rated.map((c) => option(c, true));
  if (ratedOptions.length) ratedOptions[0].heading = 'Already rated';
  options.push(...ratedOptions);

  return (
    <ChoiceGroup
      legend="Which course?"
      subtitle={`Courses we know Prof. ${lastName(professor.name)} has taught.`}
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
  rated: string[];
  onPick: (c: RateCourse) => void;
  onBack: () => void;
}

export function OtherCourseStep({ rated, onPick, onBack }: OtherCourseStepProps) {
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

  const settled = found !== null && found.q === term ? found.items : null;
  const code = typed.replace(/\s+/g, '').toUpperCase();
  const canAdd = settled !== null && settled.length === 0 && NEW_CODE.test(code);

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
        <div className="rate-suggs">
          {settled.map((c) => {
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
          })}
        </div>
      )}
      {canAdd && (
        <>
          <p className="rate-hint rate-note">{formatCode(code)} isn't in our catalog yet. Name it and it's added with your rating.</p>
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
        {canAdd && (
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
