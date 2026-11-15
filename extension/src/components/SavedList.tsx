import { useEffect, useState } from 'react';
import { fetchProfessor } from '../api';
import { readSaved, unsave, SAVED_KEY, type SavedProfessor } from '../utils/saved';
import { ChevronIcon, CloseIcon } from './icons';
import { score } from '../utils/format';

/** Live, not a copy taken when it was saved: a number frozen weeks ago would
 *  quietly disagree with the professor's page. */
type Live = { rating: number | null; dept: string | null } | null;

/** More saved professors than this and the group starts collapsed, so a long
 *  list doesn't push Recent Searches out of the popup. */
const OPEN_UP_TO = 4;

/** Saved professors, above Recent Searches on both search screens. Shown even
 *  with nothing saved, as Saved (0), so the feature is there to discover.
 *  Styled by Search.css, the screen it sits on. */
export default function SavedList({
  onOpen,
  exclude = [],
}: {
  onOpen: (slug: string) => void;
  /** Professors already in the comparison, left out like Search's results. */
  exclude?: string[];
}) {
  const saved = useSaved();
  const items = saved.filter((item) => !exclude.includes(item.slug));
  const [live, setLive] = useState<Record<string, Live>>({});
  // Null until the student opens or closes it: until then the group is open
  // for a short list and closed for a long one.
  const [open, setOpen] = useState<boolean | null>(null);
  const isOpen = open ?? items.length <= OPEN_UP_TO;

  useEffect(() => {
    let alive = true;
    // fetchProfessor is cached, so opening one of these afterwards is free.
    for (const { slug } of saved) {
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
  }, [saved]);

  return (
    <section className="search-section" aria-label="Saved professors">
      <button
        className="section-label saved-toggle"
        type="button"
        aria-expanded={isOpen}
        aria-controls="saved-list"
        onClick={() => setOpen(!isOpen)}
      >
        <ChevronIcon className={isOpen ? 'saved-chev open' : 'saved-chev'} />
        Saved
        <span className="saved-count">({items.length})</span>
      </button>
      <div id="saved-list" hidden={!isOpen}>
        {items.length === 0 ? (
          <p className="muted search-empty">Professors you save will show up here.</p>
        ) : (
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
        )}
      </div>
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
