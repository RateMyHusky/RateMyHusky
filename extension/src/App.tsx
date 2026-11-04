import { useEffect, useState } from 'react';
import Header from './components/Header';
import Overview from './screens/Overview';
import Compare from './screens/Compare';
import Courses from './screens/Courses';
import Settings from './screens/Settings';
import { applyTheme, loadTheme, saveTheme, type Theme } from './utils/theme';

// Search lands separately and will pick these; until then the popup opens on
// a fixed professor and compares a fixed pair.
const DEMO_SLUG = 'john-rachlin';
const DEMO_COMPARE = ['john-rachlin', 'david-kaeli'];

type View = 'overview' | 'compare' | 'courses' | 'settings';

export default function App() {
  // A stack rather than one view. The gear is live on every screen, so a Back
  // hard-wired to Overview dropped anyone who opened Settings from Compare
  // out of the comparison they were reading.
  const [stack, setStack] = useState<View[]>(['overview']);
  const [theme, setTheme] = useState<Theme>(loadTheme);
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
      <main className="body">
        {view === 'overview' && (
          <Overview
            slug={DEMO_SLUG}
            onCompare={() => {
              // A new comparison starts with nobody removed. Back from
              // Settings pops the stack instead of coming through here, so a
              // round trip there keeps the drops.
              setDropped([]);
              open('compare');
            }}
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
        {view === 'courses' && <Courses slug={DEMO_SLUG} />}
        {view === 'settings' && <Settings theme={theme} onTheme={setTheme} />}
      </main>
    </>
  );
}
