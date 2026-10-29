import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import type { ReactNode } from 'react';
import { maintenanceGuard } from '../api/api';

const API_BASE = import.meta.env.VITE_API_URL || '';
const TOKEN_KEY = 'auth_token';
const ME_RETRY_MS = 5000;

interface User {
  email: string;
  name: string;
  picture: string;
}

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: () => void;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  loading: true,
  login: () => {},
  logout: async () => {},
});

function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

function storeToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

// The redirect sign-in returns its token in the URL fragment. Only accept one this
// tab asked for: otherwise a link carrying someone else's token would silently sign
// the visitor into that account (and their bookmarks and Ask questions would land in it).
const PENDING_KEY = 'auth_redirect_started';
const PENDING_MAX_AGE_MS = 15 * 60 * 1000;

function startRedirectSignIn(returnTo: string) {
  try {
    sessionStorage.setItem(PENDING_KEY, String(Date.now()));
  } catch {
    // storage blocked: the returning token will be ignored and the user stays signed out
  }
  window.location.href = `${API_BASE}/api/auth/google?returnTo=${encodeURIComponent(returnTo)}`;
}

function takeRedirectSignIn(): boolean {
  try {
    const started = Number(sessionStorage.getItem(PENDING_KEY));
    sessionStorage.removeItem(PENDING_KEY);
    return Number.isFinite(started) && started > 0 && Date.now() - started < PENDING_MAX_AGE_MS;
  } catch {
    return false;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const popupRef = useRef<Window | null>(null);

  const fetchUser = useCallback(function check(retry = true): Promise<void> {
    const token = getStoredToken();
    if (!token) {
      setUser(null);
      return Promise.resolve();
    }
    // A 429 (campus NAT shares one IP's limit), a 5xx or a dropped request says
    // nothing about the token: keep it and the current user, and try once more.
    const transient = () => {
      if (retry) setTimeout(() => check(false), ME_RETRY_MS);
    };
    return fetch(`${API_BASE}/api/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(res => {
        // Maintenance redirect: tab is navigating away, keep the token.
        if (maintenanceGuard(res)) return undefined;
        if (res.status === 401) return null;
        if (!res.ok) {
          transient();
          return undefined;
        }
        return res.json();
      })
      .then(data => {
        // Another tab changed the token while this was in flight; the check that
        // change started will answer for the new one.
        if (data === undefined || getStoredToken() !== token) return;
        if (data) {
          setUser(data);
        } else {
          // Clearing fires a storage event that signs out every tab: only for a rejected token.
          clearToken();
          setUser(null);
        }
      })
      .catch(transient);
  }, []);

  // Check for token in URL fragment (mobile redirect flow)
  useEffect(() => {
    const hash = window.location.hash;
    if (hash.includes('auth_token=')) {
      const token = hash.split('auth_token=')[1]?.split('&')[0];
      if (token && takeRedirectSignIn()) storeToken(token);
      // Strip the token from the URL either way so it isn't left in history.
      window.history.replaceState(null, '', window.location.pathname + window.location.search);
    }
    // Handle auth errors from backend redirect
    const params = new URLSearchParams(window.location.search);
    const authError = params.get('auth_error');
    if (authError) {
      params.delete('auth_error');
      const cleaned = params.toString();
      window.history.replaceState(null, '', window.location.pathname + (cleaned ? `?${cleaned}` : ''));
    }
  }, []);

  useEffect(() => {
    fetchUser().finally(() => setLoading(false));
  }, [fetchUser]);

  // Listen for popup completion
  useEffect(() => {
    const handler = (e: MessageEvent) => {
      const expectedOrigin = API_BASE ? new URL(API_BASE).origin : window.location.origin;
      if (e.origin !== expectedOrigin) return;
      if (e.data?.type === 'auth_complete' && e.data?.token) {
        storeToken(e.data.token);
        fetchUser();
        popupRef.current = null;
      }
      // Backwards compat
      if (e.data === 'auth_complete') {
        fetchUser();
        popupRef.current = null;
      }
    };
    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, [fetchUser]);

  // The token is shared by every tab, so a sign-in or sign-out in one tab updates
  // the others instead of leaving them showing the old account.
  useEffect(() => {
    const handler = (e: StorageEvent) => {
      if (e.key === TOKEN_KEY || e.key === null) fetchUser();
    };
    window.addEventListener('storage', handler);
    return () => window.removeEventListener('storage', handler);
  }, [fetchUser]);

  const login = useCallback(() => {
    const isMobile = /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);
    const returnTo = window.location.pathname + window.location.search;

    if (isMobile) {
      startRedirectSignIn(returnTo);
      return;
    }

    // Desktop: popup flow
    const w = 500;
    const h = 600;
    const left = window.screenX + (window.outerWidth - w) / 2;
    const top = window.screenY + (window.outerHeight - h) / 2;

    const popup = window.open(
      `${API_BASE}/api/auth/google?popup=1`,
      'signin',
      `width=${w},height=${h},left=${left},top=${top},popup=1`,
    );

    if (popup) {
      popupRef.current = popup;
      const interval = setInterval(() => {
        if (popup.closed) {
          clearInterval(interval);
          fetchUser();
          popupRef.current = null;
        }
      }, 500);
    } else {
      startRedirectSignIn(returnTo);
    }
  }, [fetchUser]);

  const logout = useCallback(async () => {
    const token = getStoredToken();
    const res = await fetch(`${API_BASE}/api/auth/logout`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    clearToken();
    setUser(null);
    maintenanceGuard(res);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
