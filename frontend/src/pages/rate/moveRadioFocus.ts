import type { KeyboardEvent } from 'react';

// A radiogroup's onKeyDown. Arrow keys move focus only; Enter, Space and click select.
export function moveRadioFocus(e: KeyboardEvent<HTMLElement>) {
  const step = e.key === 'ArrowDown' || e.key === 'ArrowRight' ? 1 : e.key === 'ArrowUp' || e.key === 'ArrowLeft' ? -1 : 0;
  if (!step) return;
  const radios = Array.from(e.currentTarget.querySelectorAll<HTMLButtonElement>('[role="radio"]'));
  const at = radios.indexOf(document.activeElement as HTMLButtonElement);
  if (at < 0) return;
  e.preventDefault();
  radios[(at + step + radios.length) % radios.length].focus();
}
