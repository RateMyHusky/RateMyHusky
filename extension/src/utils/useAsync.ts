import { useEffect, useState } from 'react';
import { errorMessage } from '../api';

/** Loading, loaded, or failed with a sentence the screen can print as-is. */
export type Async<T> =
  | { status: 'loading' }
  | { status: 'ready'; data: T }
  | { status: 'error'; message: string };

/** Overview, Compare and Courses each fetch on mount, and each used to carry
 *  its own copy of this state type and effect — so a fix to one, like the
 *  reset on a slug change, had to be made three times.
 *
 *  `key` is the dependency rather than `load`: callers pass a fresh closure on
 *  every render, and depending on that would refetch on every render. */
export function useAsync<T>(load: () => Promise<T>, key: string): Async<T> {
  const [state, setState] = useState<Async<T>>({ status: 'loading' });

  useEffect(() => {
    // Cleared on unmount and on a key change, so a slow response for the
    // previous key can't land on top of the current one.
    let live = true;
    // Without this a key change keeps the previous result — name, scores and
    // links — on screen until the new one resolves.
    setState({ status: 'loading' });
    load()
      .then((data) => live && setState({ status: 'ready', data }))
      .catch((err) => live && setState({ status: 'error', message: errorMessage(err) }));
    return () => {
      live = false;
    };
  }, [key]);

  return state;
}
