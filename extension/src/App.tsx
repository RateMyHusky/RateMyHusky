import { useEffect, useState } from 'react';
import Header from './components/Header';
import Overview from './screens/Overview';
import Compare from './screens/Compare';
import Settings from './screens/Settings';
import { applyTheme, loadTheme, saveTheme, type Theme } from './utils/theme';

// Search lands separately and will pick these; until then the popup opens on
// a fixed professor and compares a fixed pair.
const DEMO_SLUG = 'john-rachlin';
const DEMO_COMPARE = ['john-rachlin', 'david-kaeli'];

type View = 'overview' | 'compare' | 'settings';

export default function App() {
  const [view, setView] = useState<View>('overview');
  const [theme, setTheme] = useState<Theme>(loadTheme);

  // main.tsx applies the stored theme before the first paint; this is for the
  // changes the user makes afterwards.
  useEffect(() => {
    applyTheme(theme);
    saveTheme(theme);
  }, [theme]);

  return (
    <>
      <Header
        onBack={view === 'overview' ? undefined : () => setView('overview')}
        // Undefined on the settings screen itself, which greys the gear out —
        // the one place the button has nowhere to go.
        onSettings={view === 'settings' ? undefined : () => setView('settings')}
      />
      <main className="body">
        {view === 'overview' && (
          <Overview slug={DEMO_SLUG} onCompare={() => setView('compare')} />
        )}
        {view === 'compare' && <Compare slugs={DEMO_COMPARE} />}
        {view === 'settings' && <Settings theme={theme} onTheme={setTheme} />}
      </main>
    </>
  );
}
