import { useState, useRef, useEffect, useId } from 'react';
import './Dropdown.css';

interface DropdownOption {
  value: string;
  label: string;
}

interface DropdownProps {
  options: DropdownOption[];
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
  onOpenChange?: (open: boolean) => void;
  ariaLabel?: string;
  ariaLabelledBy?: string;
  triggerRef?: React.Ref<HTMLButtonElement>;
}

const Dropdown = ({ options, value, onChange, placeholder, className = '', onOpenChange, ariaLabel, ariaLabelledBy, triggerRef }: DropdownProps) => {
  const [isOpen, setOpenState] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const setIsOpen = (o: boolean) => { setOpenState(o); if (!o) setActiveIndex(-1); onOpenChange?.(o); };
  const ref = useRef<HTMLDivElement>(null);
  const byKeyboard = useRef(false);   // the last open or move came from a key, not the mouse
  const listId = useId();

  const selected = options.find((o) => o.value === value);
  const selectedIndex = options.findIndex((o) => o.value === value);
  const displayLabel = selected ? selected.label : placeholder || 'Select...';

  /* close on outside click */
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpenState(false);
        setActiveIndex(-1);
        onOpenChange?.(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [onOpenChange]);

  /* Focus stays on the trigger, so the page doesn't follow a keyboard move down a list that runs off
     screen: scroll the option into view. Never for the mouse, or the page jumps under the cursor. */
  useEffect(() => {
    if (isOpen && byKeyboard.current) document.getElementById(`${listId}-${activeIndex}`)?.scrollIntoView({ block: 'nearest' });
  }, [isOpen, activeIndex, listId]);

  const handleSelect = (val: string) => {
    onChange(val);
    setIsOpen(false);
  };

  const openAt = (i: number) => {
    setActiveIndex(i);
    if (!isOpen) setIsOpen(true);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    byKeyboard.current = true;
    const last = options.length - 1;
    const from = isOpen ? activeIndex : selectedIndex;
    if (e.key === 'Escape') {
      if (!isOpen) return;
      e.preventDefault();
      setIsOpen(false);
    } else if (e.key === 'Tab') {
      if (isOpen) setIsOpen(false);
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!isOpen) openAt(Math.max(selectedIndex, 0));
      else openAt(Math.min(last, Math.max(0, activeIndex + (e.key === 'ArrowDown' ? 1 : -1))));
    } else if (e.key === 'Home' || e.key === 'End') {
      e.preventDefault();
      openAt(e.key === 'Home' ? 0 : last);
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      if (!isOpen) openAt(Math.max(selectedIndex, 0));
      else if (options[activeIndex]) handleSelect(options[activeIndex].value);
    } else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      const ch = e.key.toLowerCase();
      for (let k = 1; k <= options.length; k++) {
        const idx = (from + k) % options.length;
        if (options[idx].label.toLowerCase().startsWith(ch)) {
          openAt(idx);
          break;
        }
      }
    }
  };

  return (
    <div className={`dropdown ${className}`} ref={ref}
      onClick={(e) => { if (e.target === e.currentTarget) setIsOpen(false); }}
      onBlur={(e) => { if (isOpen && e.relatedTarget && !ref.current?.contains(e.relatedTarget as Node)) setIsOpen(false); }}
    >
      <button
        className={`dropdown-trigger ${isOpen ? 'open' : ''} ${!selected ? 'placeholder' : ''}`}
        onClick={(e) => { byKeyboard.current = e.detail === 0; if (isOpen) setIsOpen(false); else openAt(Math.max(selectedIndex, 0)); }}
        onKeyDown={handleKeyDown}
        onKeyUp={(e) => { if (e.key === ' ') e.preventDefault(); }}
        ref={triggerRef}
        type="button"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-controls={listId}
        aria-label={ariaLabel}
        aria-labelledby={ariaLabelledBy}
        aria-activedescendant={isOpen && activeIndex >= 0 ? `${listId}-${activeIndex}` : undefined}
      >
        <span className="dropdown-trigger-label">{displayLabel}</span>
        <svg
          className={`dropdown-chevron ${isOpen ? 'rotated' : ''}`}
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {isOpen && (
        <ul className="dropdown-menu" role="listbox" id={listId} onAnimationEnd={(e) => { if (e.target === e.currentTarget && byKeyboard.current) document.getElementById(`${listId}-${activeIndex}`)?.scrollIntoView({ block: 'nearest' }); }} onMouseDown={(e) => { if (e.target === e.currentTarget) setIsOpen(false); }}>
          {options.map((opt, i) => (
            <li
              key={opt.value}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={opt.value === value}
              className={`dropdown-item ${opt.value === value ? 'active' : ''} ${i === activeIndex ? 'focused' : ''}`}
              onMouseDown={(e) => e.preventDefault()}
              onMouseEnter={() => { byKeyboard.current = false; setActiveIndex(i); }}
              onClick={() => handleSelect(opt.value)}
              style={{ animationDelay: `${i * 0.04}s` }}
            >
              {opt.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default Dropdown;