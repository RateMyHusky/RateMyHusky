import { useEffect, useState } from 'react';
import Header from './components/Header';
import Search from './screens/Search';
import Overview from './screens/Overview';
import Reviews from './screens/Reviews';
import Compare from './screens/Compare';
import Courses from './screens/Courses';
import Settings from './screens/Settings';
import { applyTheme, loadTheme, saveTheme, type Theme } from './utils/theme';

/** `pick` is Search choosing a professor for Compare rather than opening one. */
type View = 'search' | 'overview' | 'reviews' | 'courses' | 'compare' | 'pick' | 'settings';

/** `openSlug` is set when a rating badge on Banner opened the popup: it starts
 *  on that professor, with Search one Back away like any other visit. */
export default function App({ openSlug }: { openSlug?: string }) {
  // A stack rather than one view. The gear is live on every screen, so a Back
  // hard-wired to Overview dropped anyone who opened Settings from Compare
  // out of the comparison they were reading. Every screen is reached one way
  // and left by Back, so the stack only ever grows along the path taken.
  const [stack, setStack] = useState<View[]>(openSlug ? ['search', 'overview'] : ['search']);
  const [theme, setTheme] = useState<Theme>(loadTheme);
  const [slug, setSlug] = useState<string | null>(openSlug ?? null);
  const [comparing, setComparing] = useState<string[]>([]);
  // Compare's removed professors live up here because the screen unmounts on
  // every trip to Settings, and remounting brought them all back.
  const [dropped, setDropped] = useState<string[]>([]);

  const view = stack[stack.length - 1];
  const open = (next: View) => setStack((s) => [...s, next]);
  const back = () => setStack((s) => s.slice(0, -1));

  // main.tsx applies the stored theme before the first paint; this is for the
  // changes the user makes afterwards.
  useEffect(() => {
    applyTheme(theme);
    saveTheme(theme);
  }, [theme]);

  function openProfessor(next: string): void {
    setSlug(next);
    open('overview');
  }

  /** Overview's Compare starts a fresh comparison with that professor in it,
   *  then goes straight to picking the second — one professor isn't a
   *  comparison. */
  function startCompare(): void {
    if (!slug) return;
    setComparing([slug]);
    setDropped([]);
    open('pick');
  }

  /** Whoever was removed stays removed; the pick joins the rest. The picker
   *  then gives way to Compare: back onto it when it was already open,
   *  replacing the picker when this is the comparison's first pick, so Back
   *  from Compare returns to the Overview it started from. */
  function addToCompare(next: string): void {
    setComparing((c) => [...c.filter((s) => !dropped.includes(s) && s !== next), next]);
    setDropped([]);
    setStack((s) => {
      const below = s.slice(0, -1);
      return below[below.length - 1] === 'compare' ? below : [...below, 'compare'];
    });
  }

  const live = comparing.filter((s) => !dropped.includes(s));

  return (
    <>
      <Header
        onBack={stack.length > 1 ? back : undefined}
        // Undefined on the settings screen itself, which greys the gear out —
        // the one place the button has nowhere to go.
        onSettings={view === 'settings' ? undefined : () => open('settings')}
      />
      <main className="body">
        {view === 'search' && <Search onPick={openProfessor} showSaved />}
        {view === 'pick' && (
          <Search onPick={addToCompare} heading="Add to comparison" exclude={live} />
        )}
        {view === 'overview' && slug && (
          <Overview
            slug={slug}
            onCompare={startCompare}
            onReviews={() => open('reviews')}
            onCourses={() => open('courses')}
          />
        )}
        {view === 'reviews' && slug && <Reviews slug={slug} />}
        {view === 'courses' && slug && <Courses slug={slug} />}
        {view === 'compare' && (
          <Compare
            slugs={comparing}
            dropped={dropped}
            onDrop={(s) => setDropped((d) => [...d, s])}
            onAdd={() => open('pick')}
          />
        )}
        {view === 'settings' && <Settings theme={theme} onTheme={setTheme} />}
      </main>
    </>
  );
}
