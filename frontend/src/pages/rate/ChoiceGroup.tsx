import { Fragment, useEffect, useId, useState } from 'react';
import type { ReactNode } from 'react';
import { moveRadioFocus } from './moveRadioFocus';

export interface ChoiceOption<T> {
  value: T;
  label: ReactNode;
  aria: string;
  className?: string;
  digit?: number;
  heading?: string;
}

interface ChoiceGroupProps<T> {
  legend: string;
  subtitle?: string;
  options: ChoiceOption<T>[];
  value?: T;
  onPick: (v: T) => void;
  layout: 'stack' | 'grid';
}

export function BackLink({ onBack, disabled }: { onBack: () => void; disabled?: boolean }) {
  return <button type="button" className="rate-back" disabled={disabled} onClick={onBack}>‹ Back</button>;
}

/* On mobile this renders in place; from 1024px it is the pinned footer, the step's action with the ghost link under it; Back is hidden there because it lives in the top row. */
export function StepFoot({ onBack, backDisabled, children }: { onBack?: () => void; backDisabled?: boolean; children?: ReactNode }) {
  return (
    <div className="rate-foot">
      <span className="rate-foot-actions">{children}</span>
      {onBack && <BackLink onBack={onBack} disabled={backDisabled} />}
    </div>
  );
}

export function ChoiceGroup<T>({ legend, subtitle, options, value, onPick, layout }: ChoiceGroupProps<T>) {
  const headingId = useId();
  // The picked value, not its position, so the pop stays on the picked tile if the options reorder.
  const [popped, setPopped] = useState<T | null>(null);

  // Keys 1-5 pick the option whose digit matches, never by position.
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.repeat || e.ctrlKey || e.metaKey || e.altKey) return;
      const el = document.activeElement;
      if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement) return;
      if (!/^[1-5]$/.test(e.key)) return;
      const hit = options.find((o) => o.digit === Number(e.key));
      if (!hit) return;
      setPopped(hit.value);
      onPick(hit.value);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [options, onPick]);

  const checked = options.findIndex((o) => o.value === value);
  const tabStop = checked < 0 ? 0 : checked;

  return (
    <>
      <h1 id={headingId} className="rate-q" tabIndex={-1}>{legend}</h1>
      {subtitle && <p className="rate-sub">{subtitle}</p>}
      <div
        role="radiogroup"
        aria-labelledby={headingId}
        className={`rate-choices rate-choices-${layout}`}
        onKeyDown={moveRadioFocus}
      >
        {options.map((o, i) => (
          <Fragment key={i}>
            {/* Hidden from screen readers, since a radiogroup holds only radios; the tiles under it say so in their labels. */}
            {o.heading && <h2 className="rate-group" aria-hidden="true">{o.heading}</h2>}
            <button
              type="button"
              role="radio"
              aria-checked={i === checked}
              aria-label={o.aria}
              tabIndex={i === tabStop ? 0 : -1}
              className={`rate-opt${i === checked ? ' on' : ''}${o.className ? ` ${o.className}` : ''}${o.value === popped ? ' pop' : ''}`}
              onClick={() => { setPopped(o.value); onPick(o.value); }}
            >
              {o.label}
            </button>
          </Fragment>
        ))}
      </div>
    </>
  );
}
