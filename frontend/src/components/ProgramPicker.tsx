import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { MAX_PROGRAMS, OTHER, searchPrograms } from '../utils/programSearch';
import type { Program } from '../utils/programSearch';

interface ProgramPickerProps {
  label: string;
  programs: Program[];
  selected: string[];
  onChange: (next: string[]) => void;
  addLabel: string;
  otherLabel: string;
}

const ProgramPicker = ({ label, programs, selected, onChange, addLabel, otherLabel }: ProgramPickerProps) => {
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const [adding, setAdding] = useState(false);
  const listId = useId();
  const addRef = useRef<HTMLButtonElement>(null);
  const justPicked = useRef(false);

  const groups = useMemo(() => searchPrograms(programs, query, selected), [programs, query, selected]);
  const flat = groups.flatMap((g) => g.programs);
  const full = selected.length >= MAX_PROGRAMS;
  // The input shows until the first pick, then hides behind the add button.
  const showInput = !full && (selected.length === 0 || adding);

  const add = (name: string) => {
    if (full || selected.includes(name)) return;
    justPicked.current = true;
    onChange([...selected, name]);
    setQuery('');
    setActive(0);
    setAdding(false);
  };

  // The focused input unmounts on a pick; hand focus to the add button that replaces it.
  useEffect(() => {
    if (!justPicked.current) return;
    justPicked.current = false;
    addRef.current?.focus();
  }, [selected]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown' && flat.length) {
      e.preventDefault();
      setActive((i) => Math.min(i + 1, flat.length - 1));
    } else if (e.key === 'ArrowUp' && flat.length) {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter' && flat[active]) {
      e.preventDefault();
      add(flat[active].name);
    } else if (e.key === 'Escape') {
      setQuery('');
    }
  };

  return (
    <div className="program-picker">
      <label className="profile-label" htmlFor={`${listId}-input`}>{label}</label>
      {selected.map((name) => {
        const text = name === OTHER ? 'Not listed' : name;
        return (
          <span className="profile-chip" key={name}>
            {text}
            <button type="button" aria-label={`Remove ${text}`} onClick={() => onChange(selected.filter((n) => n !== name))}>
              &#10005;
            </button>
          </span>
        );
      })}
      {showInput && (
        <>
          <input
            id={`${listId}-input`}
            className="profile-field"
            type="text"
            role="combobox"
            aria-expanded={flat.length > 0}
            aria-controls={listId}
            aria-activedescendant={flat[active] ? `${listId}-${active}` : undefined}
            autoComplete="off"
            autoFocus={adding}
            value={query}
            onChange={(e) => { setQuery(e.target.value); setActive(0); }}
            onKeyDown={onKeyDown}
          />
          {flat.length > 0 && (
            <div className="profile-menu" id={listId} role="listbox" aria-label={label}>
              {groups.map((g) => (
                <div role="group" aria-label={g.college} key={g.college}>
                  <div className="profile-menu-group">{g.college}</div>
                  {g.programs.map((p) => {
                    const i = flat.indexOf(p);
                    return (
                      <div
                        key={p.name}
                        id={`${listId}-${i}`}
                        role="option"
                        aria-selected={i === active}
                        className={i === active ? 'profile-menu-option hi' : 'profile-menu-option'}
                        onMouseDown={(e) => { e.preventDefault(); add(p.name); }}
                      >
                        {p.name}
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>
          )}
        </>
      )}
      {!showInput && !full && (
        <button type="button" className="profile-add" ref={addRef} onClick={() => setAdding(true)}>{addLabel}</button>
      )}
      {!full && !selected.includes(OTHER) && (
        <button type="button" className="profile-other" onClick={() => add(OTHER)}>{otherLabel}</button>
      )}
    </div>
  );
};

export default ProgramPicker;
