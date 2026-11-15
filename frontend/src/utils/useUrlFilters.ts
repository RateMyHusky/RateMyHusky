import { useCallback, useEffect, useRef, useState, type SetStateAction } from 'react';
import { useLocation, useNavigationType, useSearchParams } from 'react-router-dom';

/**
 * A catalog's filters, kept in the URL so the view is shareable and Back/Forward step through it.
 * setFilters(next, true) adds a history entry (a discrete pick); without it the current entry is
 * replaced, so typing and slider drags aren't a keystroke-by-keystroke Back.
 *
 * On Back/Forward the URL wins: until the popped entry has been loaded into `filters`, they still
 * describe the page being left, and writing them would undo the Back. The first page load is a POP
 * too, so an odd URL such as ?sort=bogus is left as typed until the first change.
 */
export function useUrlFilters<F extends object>(
  parse: (sp: URLSearchParams) => F,
  build: (filters: F) => URLSearchParams,
) {
  const [searchParams, setSearchParams] = useSearchParams();
  const navType = useNavigationType();
  const { key: locationKey } = useLocation();
  const pushNext = useRef(false);
  const poppedKey = useRef<string | null>(null);   // the Back/Forward entry already loaded into filters
  const [filters, setFilterState] = useState<F>(() => parse(searchParams));

  useEffect(() => {
    const push = pushNext.current;
    pushNext.current = false;
    if (navType !== 'POP') poppedKey.current = null;   // a push or replace moved on; a later return to an old entry must reload it
    if (navType === 'POP' && poppedKey.current !== locationKey) return;
    const next = build(filters);
    if (next.toString() !== searchParams.toString()) {
      setSearchParams(next, { replace: !push });
    }
  }, [filters, searchParams, setSearchParams, navType, locationKey, build]);

  // Keep in-memory filters synced when the URL changes externally (Back/Forward, shared links).
  useEffect(() => {
    if (navType === 'POP') poppedKey.current = locationKey;
    const fromUrl = parse(searchParams);
    setFilterState(prev =>
      (Object.keys(fromUrl) as (keyof F)[]).every(k => prev[k] === fromUrl[k]) ? prev : fromUrl);
  }, [searchParams, navType, locationKey, parse]);

  const setFilters = useCallback((next: SetStateAction<F>, push = false) => {
    if (push) pushNext.current = true;
    setFilterState(next);
  }, []);

  return { filters, setFilters, searchParams };
}
