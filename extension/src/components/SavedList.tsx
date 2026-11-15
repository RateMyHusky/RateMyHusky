import { useEffect, useState } from 'react';
import { fetchProfessor } from '../api';
import { readSaved, removeSaved, entryId, SAVED_KEY } from '../banner/saved';
import type { SavedEntry } from '../banner/messages';
import { ChevronIcon, CloseIcon } from './icons';
import { score } from '../utils/format';

/** Live, not the rating at the moment of saving: a number frozen weeks ago
 *  would quietly disagree with the professor's page. */
type Rating = { rating: number | null } | null;

/** Professors saved from Banner, on the home screen. Renders nothing until
 *  something's been saved, so a student who never opens Banner never sees an
 *  empty section about a feature they don't use. Styled by Search.css, the
 *  only screen it sits on. */
export default function SavedList({ onOpen }: { onOpen: (slug: string) => void }) {
  const [items, setItems] = useState<SavedEntry[]>([]);
  const [ratings, setRatings] = useState<Record<string, Rating>>({});

  // chrome.storage is missing outside the extension (a plain Vite preview), so
  // the section just stays empty there.
  const storage = typeof chrome !== 'undefined' ? chrome.storage : undefined;

  useEffect(() => {
    if (!storage) return;
    let alive = true;
    const refresh = () =>
      readSaved().then(
        (saved) => alive && setItems(saved),
        () => alive && setItems([]),
      );
    void refresh();
    // A save on the Banner tab while the popup is open shows up straight away.
    const onChange = (changes: Record<string, chrome.storage.StorageChange>, area: string) => {
      if (area === 'local' && changes[SAVED_KEY]) void refresh();
    };
    storage.onChanged.addListener(onChange);
    return () => {
      alive = false;
      storage.onChanged.removeListener(onChange);
    };
  }, [storage]);

  useEffect(() => {
    let alive = true;
    // fetchProfessor is cached, so a professor saved for two courses is one
    // request, and opening them afterwards costs nothing.
    for (const slug of new Set(items.map((s) => s.slug))) {
      fetchProfessor(slug).then(
        (p) => alive && setRatings((r) => ({ ...r, [slug]: { rating: p.summary.rating } })),
        () => alive && setRatings((r) => ({ ...r, [slug]: null })),
      );
    }
    return () => {
      alive = false;
    };
  }, [items]);

  if (items.length === 0) return null;

  return (
    <section className="search-section" aria-label="Saved from Banner">
      <p className="section-label">Saved from Banner</p>
      <ul className="row-list">
        {items.map((item) => {
          const r = ratings[item.slug];
          return (
            <li key={entryId(item)} className="row-wrap">
              <button className="row" type="button" onClick={() => onOpen(item.slug)}>
                <span className="row-main">
                  <span className="row-title">{item.name}</span>
                  <span className="row-meta">{item.course}</span>
                </span>
                {r?.rating != null && (
                  <span className="row-score">
                    <span className="row-star" aria-hidden="true">
                      ★
                    </span>
                    {score(r.rating)}
                  </span>
                )}
                <ChevronIcon className="row-chev" />
              </button>
              <button
                className="row-remove"
                type="button"
                onClick={() => void removeSaved(item)}
                aria-label={`Remove ${item.name} from saved`}
                title="Remove"
              >
                <CloseIcon />
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
