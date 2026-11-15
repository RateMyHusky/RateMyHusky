import { useEffect, useState } from 'react';
import Header from './components/Header';
import Overview from './screens/Overview';
import Compare from './screens/Compare';
import Courses from './screens/Courses';
import Settings from './screens/Settings';
import Saved from './screens/Saved';
import Search from './screens/Search';
import { applyTheme, loadTheme, saveTheme, type Theme } from './utils/theme';

// Search lands separately and will pick these; until then the popup opens on
// a fixed professor and compares a fixed pair.
const DEMO_SLUG = 'john-rachlin';
const DEMO_COMPARE = ['john-rachlin', 'david-kaeli'];

type View = 'search' | 'overview' | 'compare' | 'courses' | 'settings' | 'saved';

export default function App() {
  // A stack rather than one view. The gear is live on every screen, so a Back
  // hard-wired to Overview dropped anyone who opened Settings from Compare
  // out of the comparison they were reading.
  const [stack, setStack] = useState<View[]>(['search']);
  const [theme, setTheme] = useState<Theme>(loadTheme);
  const [selectedSlug, setSelectedSlug] = useState(DEMO_SLUG);
  // Compare's removed professors live up here because the screen unmounts on
  // every trip to Settings, and remounting brought them all back.
  const [dropped, setDropped] = useState<string[]>([]);

  const view = stack[stack.length - 1];
  const open = (next: View) => setStack((s) => [...s, next]);

  // main.tsx applies the stored theme before the first paint; this is for the
  // changes the user makes afterwards.
  useEffect(() => {
    applyTheme(theme);
    saveTheme(theme);
  }, [theme]);

  return (
    <>
      <Header
        onBack={stack.length > 1 ? () => setStack((s) => s.slice(0, -1)) : undefined}
        // Undefined on the settings screen itself, which greys the gear out —
        // the one place the button has nowhere to go.
        onSettings={view === 'settings' ? undefined : () => open('settings')}
      />
      <nav className="popup-nav" aria-label="RateMyHusky views">
        <button type="button" onClick={() => setStack(['search'])} disabled={view === 'search'}>Search</button>
        <button type="button" onClick={() => open('overview')} disabled={view === 'overview'}>Overview</button>
        <button type="button" onClick={() => open('saved')} disabled={view === 'saved'}>Saved</button>
      </nav>
      <main className="body">
        {view === 'search' && <Search onOverview={(slug) => { setSelectedSlug(slug); open('overview'); }} />}
        {view === 'overview' && (
          <Overview
            slug={selectedSlug}
            onCompare={selectedSlug === DEMO_SLUG ? () => {
              // A new comparison starts with nobody removed. Back from
              // Settings pops the stack instead of coming through here, so a
              // round trip there keeps the drops.
              setDropped([]);
              open('compare');
            } : undefined}
            onCourses={() => open('courses')}
          />
        )}
        {view === 'compare' && (
          <Compare
            slugs={DEMO_COMPARE}
            dropped={dropped}
            onDrop={(slug) => setDropped((d) => [...d, slug])}
          />
        )}
        {view === 'courses' && <Courses slug={selectedSlug} />}
        {view === 'saved' && <Saved onOpen={(slug) => { setSelectedSlug(slug); open('overview'); }} />}
        {view === 'settings' && <Settings theme={theme} onTheme={setTheme} />}
      </main>
    </>
  );
}
