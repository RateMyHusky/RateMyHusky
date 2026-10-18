import Header from './components/Header';
import Overview from './screens/Overview';

// Search lands separately and will pick the slug; until then the popup opens
// straight onto one professor.
const DEMO_SLUG = 'john-rachlin';

export default function App() {
  return (
    <>
      <Header />
      <main className="body">
        <Overview slug={DEMO_SLUG} />
      </main>
    </>
  );
}
