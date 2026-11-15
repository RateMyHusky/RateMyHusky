import { useEffect, useState } from 'react';
import { fetchProfessor } from '../api';
import { readSaved, removeSaved, SAVED_KEY } from '../banner/saved';
import type { SavedEntry } from '../banner/messages';
import './Saved.css';

type Current = { rating: number | null; numRatings: number };

export default function Saved({ onOpen }: { onOpen: (slug: string) => void }) {
  const [items, setItems] = useState<SavedEntry[]>([]);
  const [ratings, setRatings] = useState<Record<string, Current | null>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    async function refresh() {
      try {
        const saved = await readSaved();
        if (!alive) return;
        setItems(saved);
        setLoading(false);
        setError('');
      } catch {
        if (alive) { setLoading(false); setError('Could not load saved professors.'); }
      }
    }
    void refresh();
    const onChange = (changes: { [key: string]: chrome.storage.StorageChange }, area: string) => {
      if (area === 'local' && changes[SAVED_KEY]) void refresh();
    };
    chrome.storage.onChanged.addListener(onChange);
    return () => { alive = false; chrome.storage.onChanged.removeListener(onChange); };
  }, []);

  useEffect(() => {
    let alive = true;
    const slugs = [...new Set(items.map((s) => s.slug))];
    for (const slug of slugs) {
      void fetchProfessor(slug)
        .then((p) => { if (alive) setRatings((r) => ({ ...r, [slug]: {
          rating: p.summary.rating, numRatings: p.summary.numRatings,
        } })); })
        .catch(() => { if (alive) setRatings((r) => ({ ...r, [slug]: null })); });
    }
    return () => { alive = false; };
  }, [items]);

  async function remove(item: SavedEntry) {
    try {
      await removeSaved(item);
      setItems((prev) => prev.filter((s) =>
        !(s.slug === item.slug && s.course === item.course && s.term === item.term)));
    } catch {
      setError('Could not remove saved professor.');
    }
  }

  return (
    <section className="saved-screen">
      <h1>Saved professors & courses</h1>
      <p className="muted">Saved from Banner. Ratings are loaded fresh from RateMyHusky.</p>
      {error && <p className="muted" role="alert">{error}</p>}
      {loading ? <p className="muted">Loading saved professors…</p> :
        items.length === 0 ? <p className="saved-empty">Nothing saved yet. Use Save beside a matched professor in Banner.</p> :
        <ul className="saved-list">
          {items.map((item) => {
            const current = ratings[item.slug];
            return (
              <li className="saved-item" key={JSON.stringify([item.slug, item.course, item.term])}>
                <button className="saved-open" type="button" onClick={() => onOpen(item.slug)}>
                  <strong>{item.name}</strong>
                  <small>{item.course} · term {item.term}</small>
                  <span className="saved-score">
                    {current === undefined ? 'Loading current rating…' :
                     current === null ? 'Rating unavailable' :
                     current.rating == null ? 'No ratings yet' :
                     `★ ${current.rating.toFixed(1)} · ${current.numRatings} ratings`}
                  </span>
                </button>
                <button className="saved-remove" type="button" onClick={() => void remove(item)}
                  aria-label={`Remove ${item.name} from saved`}>Remove</button>
              </li>
            );
          })}
        </ul>}
    </section>
  );
}
