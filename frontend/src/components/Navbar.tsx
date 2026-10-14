import { useState, useEffect, useLayoutEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { Link, NavLink, useLocation } from 'react-router-dom';

import { useAuth } from '../context/AuthContext';
import SignInModal from './SignInModal';
import ThemeToggle from './ThemeToggle';
import './Navbar.css';

const Navbar = () => {
  const { user, loading: authLoading, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [showSignIn, setShowSignIn] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);
  const userMenuRef = useRef<HTMLDivElement>(null);
  const [pillStyle, setPillStyle] = useState({ left: 0, width: 0, opacity: 0 });
  const [isReady, setIsReady] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const [isDark, setIsDark] = useState(() => localStorage.getItem('theme') === 'dark');

  // Sync with the ThemeToggle button in the bar (and the drawer item below)
  useEffect(() => {
    const handler = (e: Event) => {
      const dark = (e as CustomEvent<{ isDark: boolean }>).detail.isDark;
      setIsDark(dark);
    };
    window.addEventListener('themechange', handler);
    return () => window.removeEventListener('themechange', handler);
  }, []);

  // Open the sign-in modal on request from elsewhere (e.g. Ask-mode 401 in SearchBar)
  useEffect(() => {
    const handler = () => setShowSignIn(true);
    window.addEventListener('open-signin', handler);
    return () => window.removeEventListener('open-signin', handler);
  }, []);

  const toggleDark = () => {
    const next = !isDark;
    setIsDark(next);
    document.documentElement.classList.toggle('dark', next);
    localStorage.setItem('theme', next ? 'dark' : 'light');
    window.dispatchEvent(new CustomEvent('themechange', { detail: { isDark: next } }));
  };

  const updatePill = useCallback(() => {
    if (!containerRef.current) return;
    const activeLink = containerRef.current.querySelector('.nav-link.active') as HTMLElement;
    
    if (activeLink) {
      setPillStyle({
        left: activeLink.offsetLeft,
        width: activeLink.offsetWidth,
        opacity: 1
      });
    } else {
      setPillStyle(prev => ({ ...prev, opacity: 0 }));
    }
  }, []);

  // Track route changes
  useLayoutEffect(() => {
    updatePill();
  }, [location.pathname, updatePill]);

  // Handle initialization and resize via ResizeObserver
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // Measure initially
    updatePill();

    // Enable animations after first layout
    const readyTimer = setTimeout(() => setIsReady(true), 100);

    const observer = new ResizeObserver(() => {
      // Temporarily disable animation during resize for smoothness
      setIsReady(false);
      updatePill();
      // Re-enable after resize settles
      setTimeout(() => setIsReady(true), 50);
    });

    observer.observe(container);

    return () => {
      clearTimeout(readyTimer);
      observer.disconnect();
    };
  }, [updatePill]);


  // Close user dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setShowUserMenu(false);
      }
    };
    if (showUserMenu) document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [showUserMenu]);

  return (
    <>
    <nav className="navbar">
      <Link
        to="/"
        className="navbar-logo"
        onClick={(e) => {
          if (location.pathname === '/') {
            e.preventDefault();
            window.scrollTo({ top: 0, behavior: 'smooth' });
          }
        }}
      >
        <span>Rate</span>MyHusky
      </Link>

      {/* Hamburger button — mobile only */}
      <button
        className={`hamburger ${menuOpen ? 'open' : ''}`}
        onClick={() => { if (!menuOpen) window.dispatchEvent(new CustomEvent('close-filter-sidebar')); setMenuOpen(!menuOpen); }}
        aria-label="Toggle menu"
      >
        <span />
        <span />
        <span />
      </button>

      {/* Nav links — slides in on mobile */}
      <div className={`navbar-right ${menuOpen ? 'show' : ''}`}>
        <div className="nav-links-container" ref={containerRef}>
          <div 
            className={`nav-pill-background ${isReady ? 'animate' : ''}`}
            style={{
              transform: `translateX(${pillStyle.left}px)`,
              width: `${pillStyle.width}px`,
              opacity: pillStyle.opacity,
              visibility: pillStyle.opacity === 0 ? 'hidden' : 'visible'
            }}
          />
          <NavLink to="/professors" className="nav-link" onClick={() => setMenuOpen(false)}>
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
              <circle cx="9" cy="7" r="4" />
              <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
              <path d="M16 3.13a4 4 0 0 1 0 7.75" />
            </svg>
            Professors
          </NavLink>
          <NavLink to="/courses" className="nav-link" onClick={() => setMenuOpen(false)}>
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
              <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
            </svg>
            Courses
          </NavLink>
          <NavLink to="/compare" className="nav-link" onClick={() => setMenuOpen(false)}>
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="20" x2="18" y2="10" />
              <line x1="12" y1="20" x2="12" y2="4" />
              <line x1="6" y1="20" x2="6" y2="14" />
            </svg>
            Compare
          </NavLink>
        </div>

        <ThemeToggle />

        {authLoading ? null : user ? (
          <div className="navbar-user" ref={userMenuRef}>
            <button className="navbar-user-btn" onClick={() => setShowUserMenu(v => { if (!v) window.dispatchEvent(new CustomEvent('close-filter-sidebar')); return !v; })}>
              {user.picture && <img src={user.picture} alt="" className="navbar-user-avatar" referrerPolicy="no-referrer" />}
              <span className="navbar-user-name">{user.name.split(' ')[0]}</span>
            </button>
            {showUserMenu && (
              <div className="navbar-user-dropdown">
                <p className="navbar-user-email">{user.email}</p>
                <Link to="/bookmarks" className="navbar-user-link" onClick={() => { setShowUserMenu(false); setMenuOpen(false); }}>Bookmarks</Link>
                <button className="navbar-user-signout" onClick={() => { logout(); setShowUserMenu(false); setMenuOpen(false); }}>Sign Out</button>
              </div>
            )}
          </div>
        ) : (
          <button className="signin-btn" onClick={() => { setShowSignIn(true); setMenuOpen(false); }}>Sign In</button>
        )}

        <div className="navbar-util-spacer" />

        <div className="navbar-utilities">
          <button className="navbar-utility-item" onClick={() => { window.dispatchEvent(new CustomEvent('open-feedback')); setMenuOpen(false); }}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
            </svg>
            Feedback
          </button>
          <button className="navbar-utility-item" onClick={toggleDark}>
            {isDark ? (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/>
                <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
                <line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/>
                <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
              </svg>
            )}
            {isDark ? 'Light Mode' : 'Dark Mode'}
          </button>
        </div>
      </div>

    </nav>
    {(showUserMenu || menuOpen) && createPortal(
      <div className="safari-tint-sentinel" aria-hidden="true" />,
      document.body
    )}
    {/* Overlay behind mobile menu — outside nav so it covers everything */}
    {menuOpen && (
      <div
        className="navbar-overlay"
        onClick={() => setMenuOpen(false)}
        onTouchStart={() => setMenuOpen(false)}
      />
    )}
    <SignInModal open={showSignIn} onClose={() => setShowSignIn(false)} />
    </>
  );
};

export default Navbar;