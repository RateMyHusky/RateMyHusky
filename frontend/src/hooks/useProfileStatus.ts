import { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { getProfileStatus, onProfileSaved } from '../utils/profileStatus';
import type { ProfileStatus } from '../api/api';

// A failed lookup says nothing about the profile: try once more before settling on null, like /api/auth/me.
const RETRY_MS = 5000;

/* undefined while auth or the request is loading, null when signed out or the request failed twice. */
export function useProfileStatus(): ProfileStatus | null | undefined {
  const { user, loading } = useAuth();
  const [result, setResult] = useState<{ user: unknown; status: ProfileStatus | null } | undefined>();

  const [version, setVersion] = useState(0);

  // A saved profile changes the cache; re-read so later pages in this mount see it.
  useEffect(() => onProfileSaved(() => setVersion((v) => v + 1)), []);

  useEffect(() => {
    if (loading || !user) return;
    let cancelled = false;
    let retry: number | undefined;
    const load = (again: boolean) => getProfileStatus().then((status) => {
      if (cancelled) return;
      if (status === null && again) retry = window.setTimeout(() => load(false), RETRY_MS);
      else setResult({ user, status });
    });
    load(true);
    return () => { cancelled = true; window.clearTimeout(retry); };
  }, [user, loading, version]);

  if (loading) return undefined;
  if (!user) return null;
  return result?.user === user ? result.status : undefined;
}
