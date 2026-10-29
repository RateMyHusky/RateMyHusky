import { useState } from 'react';
import { ChoiceGroup, StepFoot } from './ChoiceGroup';
import { moveRadioFocus } from './moveRadioFocus';
import type { ChoiceOption } from './ChoiceGroup';
import { SEASONS, displayTerm, formatCode, lastName, splitTerm, termYears } from './rateFlow';
import type { RateCourse, RateProfessor } from './rateFlow';

const OTHER = '+other';

interface TermStepProps {
  professor: RateProfessor;
  course: RateCourse;
  selected?: string | null;
  onPick: (term: string | null) => void;
  onOther: () => void;
}

export function TermStep({ professor, course, selected, onPick, onOther }: TermStepProps) {
  const options: ChoiceOption<string>[] = course.terms.map((t) => ({ value: t, label: displayTerm(t), aria: displayTerm(t) }));
  options.push({ value: OTHER, aria: 'A different term', label: '+ A different term', className: 'dash' });
  return (
    <>
      <ChoiceGroup
        legend="When did you take it?"
        subtitle={`Terms Prof. ${lastName(professor.name)} taught ${formatCode(course.code)}, or pick any other.`}
        options={options}
        value={selected ?? undefined}
        layout="stack"
        onPick={(v) => (v === OTHER ? onOther() : onPick(v))}
      />
      {selected === null && (
        <button type="button" className="rate-ghost on" aria-pressed="true" onClick={() => onPick(null)}>Not sure</button>
      )}
    </>
  );
}

interface OtherTermStepProps {
  now: Date;
  selected?: string | null;
  onPick: (term: string | null) => void;
  onBack: () => void;
}

export function OtherTermStep({ now, selected, onPick, onBack }: OtherTermStepProps) {
  const years = termYears(now);
  const earlier = splitTerm(selected, now);
  const [season, setSeason] = useState<string | undefined>(earlier?.season);
  const [year, setYear] = useState(earlier?.year ?? years[0]);

  return (
    <>
      <h1 className="rate-q" tabIndex={-1}>When did you take it?</h1>
      <p className="rate-sub">Pick the term and year.</p>
      <div className="rate-field">
        <span id="rate-season-label" className="rate-label">Term</span>
        <div role="radiogroup" aria-labelledby="rate-season-label" className="rate-row rate-seasons" onKeyDown={moveRadioFocus}>
          {SEASONS.map((s) => (
            <button
              key={s.value}
              type="button"
              role="radio"
              aria-checked={s.value === season}
              tabIndex={s.value === (season ?? SEASONS[0].value) ? 0 : -1}
              className={`rate-opt pill${s.value === season ? ' on' : ''}`}
              onClick={() => setSeason(s.value)}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>
      <div className="rate-field">
        <span id="rate-year-label" className="rate-label">Year</span>
        <div role="radiogroup" aria-labelledby="rate-year-label" className="rate-row rate-years" onKeyDown={moveRadioFocus}>
          {years.map((y) => (
            <button
              key={y}
              type="button"
              role="radio"
              aria-checked={y === year}
              tabIndex={y === year ? 0 : -1}
              className={`rate-opt pill${y === year ? ' on' : ''}`}
              onClick={() => setYear(y)}
            >
              {y}
            </button>
          ))}
        </div>
      </div>
      <StepFoot onBack={onBack}>
        <button type="button" className="rate-btn" disabled={!season} onClick={() => onPick(`${season} ${year}`)}>
          Continue
        </button>
        <button
          type="button"
          className={`rate-ghost${selected === null ? ' on' : ''}`}
          aria-pressed={selected === null}
          onClick={() => onPick(null)}
        >
          Not sure
        </button>
      </StepFoot>
    </>
  );
}
