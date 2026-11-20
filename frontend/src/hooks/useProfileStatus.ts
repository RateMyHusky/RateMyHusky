import { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { getProfileStatus } from '../utils/profileStatus';
import type { ProfileStatus } from '../api/api';

/* undefined while auth or the request is loading, null when signed out or the request failed. */
export function useProfileStatus(): ProfileStatus | null | undefined {
  const { user, loading } = useAuth();
  const [result, setResult] = useState<{ user: unknown; status: ProfileStatus | null } | undefined>();

  useEffect(() => {
    if (loading || !user) return;
    let cancelled = false;
    getProfileStatus().then((status) => {
      if (!cancelled) setResult({ user, status });
    });
    return () => { cancelled = true; };
  }, [user, loading]);

  if (loading) return undefined;
  if (!user) return null;
  return result?.user === user ? result.status : undefined;
}
