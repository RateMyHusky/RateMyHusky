import { useState, useRef, useEffect } from 'react';
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
}

const Dropdown = ({ options, value, onChange, placeholder, className = '', onOpenChange }: DropdownProps) => {
  const [isOpen, setOpenState] = useState(false);
  const setIsOpen = (o: boolean) => { setOpenState(o); onOpenChange?.(o); };
  const ref = useRef<HTMLDivElement>(null);

  const selected = options.find((o) => o.value === value);
  const displayLabel = selected ? selected.label : placeholder || 'Select...';

  /* close on outside click */
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpenState(false);
        onOpenChange?.(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [onOpenChange]);

  const handleSelect = (val: string) => {
    onChange(val);
    setIsOpen(false);
  };

  return (
    <div className={`dropdown ${className}`} ref={ref} onClick={(e) => { if (e.target === e.currentTarget) setIsOpen(false); }}>
      <button
        className={`dropdown-trigger ${isOpen ? 'open' : ''} ${!selected ? 'placeholder' : ''}`}
        onClick={() => setIsOpen(!isOpen)}
        type="button"
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
        <ul className="dropdown-menu" onMouseDown={(e) => { if (e.target === e.currentTarget) setIsOpen(false); }}>
          {options.map((opt, i) => (
            <li
              key={opt.value}
              className={`dropdown-item ${opt.value === value ? 'active' : ''}`}
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