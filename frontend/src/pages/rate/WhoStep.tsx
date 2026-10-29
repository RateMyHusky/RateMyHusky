import { useEffect, useState } from 'react';
import { fetchDepartments, fetchSearchSuggestions } from '../../api/api';
import { useDebouncedValue } from '../../utils/useDebouncedValue';
import type { RateProfessor } from './rateFlow';
import { StepFoot } from './ChoiceGroup';

const NEW_PROFESSOR_NOTE = 'New professors show up after a quick check by our team. Your rating is saved either way.';

interface WhoStepProps {
  onPick: (p: RateProfessor) => void;
  onAddNew: (typedName: string) => void;
}

export function WhoStep({ onPick, onAddNew }: WhoStepProps) {
  const [query, setQuery] = useState('');
  const typed = query.trim();
  const debounced = useDebouncedValue(typed, 200);
  const [found, setFound] = useState<{ q: string; items: RateProfessor[] } | null>(null);

  useEffect(() => {
    if (debounced.length < 2) return;
    let cancelled = false;
    fetchSearchSuggestions(debounced, 'Professor')
      .then((rows) => {
        if (cancelled) return;
        const items = rows.flatMap((r) => (r.type === 'professor' ? [{ slug: r.slug, name: r.name, department: r.dept }] : []));
        setFound({ q: debounced, items: items.slice(0, 5) });
      })
      .catch(() => { if (!cancelled) setFound({ q: debounced, items: [] }); });
    return () => { cancelled = true; };
  }, [debounced]);

  const results = found !== null && found.q === typed ? found.items : [];

  return (
    <>
      <h1 className="rate-q" tabIndex={-1}>Who are you rating?</h1>
      <p className="rate-sub">Search by name.</p>
      <input
        type="search"
        className="rate-input rate-search"
        aria-label="Search for a professor"
        placeholder="Professor name"
        autoComplete="off"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {typed.length >= 2 && (
        <div className="rate-suggs">
          {results.map((p) => (
            <button key={p.slug} type="button" className="rate-sugg" onClick={() => onPick(p)}>
              <b>{p.name}</b>
              {p.department && <small>{p.department}</small>}
            </button>
          ))}
          <button type="button" className="rate-sugg add" onClick={() => onAddNew(typed)}>
            + Can't find them? Add a professor
          </button>
        </div>
      )}
    </>
  );
}

interface NewProfessorStepProps {
  initialName: string;
  onContinue: (p: RateProfessor) => void;
  onBack: () => void;
}

export function NewProfessorStep({ initialName, onContinue, onBack }: NewProfessorStepProps) {
  const [name, setName] = useState(initialName);
  const [department, setDepartment] = useState('');
  const [departments, setDepartments] = useState<string[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetchDepartments()
      .then((d) => { if (!cancelled) setDepartments(d); })
      .catch(() => { /* the select still offers "Not sure" */ });
    return () => { cancelled = true; };
  }, []);

  const words = name.trim().split(/\s+/).filter(Boolean);
  return (
    <>
      <h1 className="rate-q" tabIndex={-1}>Add a professor</h1>
      <p className="rate-sub">{NEW_PROFESSOR_NOTE}</p>
      <div className="rate-field">
        <label htmlFor="rate-new-name">Full name</label>
        <input
          id="rate-new-name"
          className="rate-input"
          autoComplete="off"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      <div className="rate-field">
        <label htmlFor="rate-new-dept">Department</label>
        <select id="rate-new-dept" className="rate-input" value={department} onChange={(e) => setDepartment(e.target.value)}>
          <option value="">Not sure</option>
          {departments.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
      </div>
      <p className="rate-hint rate-hint-mobile">{NEW_PROFESSOR_NOTE}</p>
      <StepFoot onBack={onBack}>
        <button
          type="button"
          className="rate-btn"
          disabled={words.length < 2}
          onClick={() => onContinue({ slug: null, name: words.join(' '), department: department || null })}
        >
          Continue
        </button>
      </StepFoot>
    </>
  );
}
