import { useEffect, useState } from 'react';
import { fetchProfessor } from '../api';
import { readSaved, unsave, SAVED_KEY, type SavedProfessor } from '../utils/saved';
import { ChevronIcon, CloseIcon } from './icons';
import { score } from '../utils/format';

/** Live, not a copy taken when it was saved: a number frozen weeks ago would
 *  quietly disagree with the professor's page. */
type Live = { rating: number | null; dept: string | null } | null;

/** Saved professors, on the home screen. Renders nothing until something's
 *  been saved, so it never shows as an empty section. Styled by Search.css,
 *  the only screen it sits on. */
export default function SavedList({ onOpen }: { onOpen: (slug: string) => void }) {
  const items = useSaved();
  const [live, setLive] = useState<Record<string, Live>>({});

  useEffect(() => {
    let alive = true;
    // fetchProfessor is cached, so opening one of these afterwards is free.
    for (const { slug } of items) {
      fetchProfessor(slug).then(
        (p) =>
          alive &&
          setLive((l) => ({
            ...l,
            [slug]: { rating: p.summary.rating, dept: p.identity.department },
          })),
        () => alive && setLive((l) => ({ ...l, [slug]: null })),
      );
    }
    return () => {
      alive = false;
    };
  }, [items]);

  if (items.length === 0) return null;

  return (
    <section className="search-section" aria-label="Saved professors">
      <p className="section-label">Saved</p>
      <ul className="row-list">
        {items.map((item) => {
          const l = live[item.slug];
          return (
            <li key={item.slug} className="row-wrap">
              <button className="row" type="button" onClick={() => onOpen(item.slug)}>
                <span className="row-main">
                  <span className="row-title">{item.name}</span>
                  {l?.dept && <span className="row-meta">{l.dept}</span>}
                </span>
                {l?.rating != null && (
                  <span className="row-score">
                    <span className="row-star" aria-hidden="true">
                      ★
                    </span>
                    {score(l.rating)}
                  </span>
                )}
                <ChevronIcon className="row-chev" />
              </button>
              <button
                className="row-remove"
                type="button"
                onClick={() => void unsave(item.slug)}
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

/** The saved list, kept current: a save or remove anywhere — another popup,
 *  this one's Overview — lands here through storage.onChanged. Empty outside
 *  the extension (a plain Vite preview), where there's no chrome.storage. */
export function useSaved(): SavedProfessor[] {
  const [items, setItems] = useState<SavedProfessor[]>([]);
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
    const onChange = (changes: Record<string, chrome.storage.StorageChange>, area: string) => {
      if (area === 'local' && changes[SAVED_KEY]) void refresh();
    };
    storage.onChanged.addListener(onChange);
    return () => {
      alive = false;
      storage.onChanged.removeListener(onChange);
    };
  }, [storage]);

  return items;
}
