import { useEffect, useState } from 'react';

/* How long search-as-you-type boxes wait after the last keystroke before searching. */
export const SEARCH_DEBOUNCE_MS = 300;

/* `value`, updated only after it has stopped changing for `delayMs`. */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}
