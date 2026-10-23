import { useEffect, useState } from 'react';
import { fetchProfessor, isUnavailable, isNotFound, type Professor } from '../api';
import StarRating from '../components/StarRating';
import { buildRows, MIN_RATINGS } from '../utils/compare';
import './Compare.css';

type State =
  | { status: 'loading' }
  | { status: 'ready'; profs: Professor[] }
  | { status: 'error'; message: string };

export default function Compare({ slugs }: { slugs: string[] }) {
  const [state, setState] = useState<State>({ status: 'loading' });
  const [dropped, setDropped] = useState<string[]>([]);

  useEffect(() => {
    let live = true;
    setState({ status: 'loading' });
    Promise.all(slugs.map(fetchProfessor))
      .then((profs) => live && setState({ status: 'ready', profs }))
      .catch((err) =>
        live &&
        setState({
          status: 'error',
          message: isNotFound(err)
            ? 'Professor not found.'
            : isUnavailable(err)
              ? "Can't reach RateMyHusky right now."
              : 'Something went wrong.',
        }),
      );
    return () => {
      live = false;
    };
  }, [slugs.join(',')]);

  if (state.status === 'loading') return <p className="muted">Loading…</p>;
  if (state.status === 'error') return <p className="muted">{state.message}</p>;

  const profs = state.profs.filter((p) => !dropped.includes(p.identity.slug));
  if (profs.length === 0) return <p className="muted">No professors to compare.</p>;

  const rows = buildRows(profs);
  const grid = { gridTemplateColumns: `76px repeat(${profs.length}, minmax(0, 1fr))` };

  return (
    <div className="compare">
      <div className="cmp-heads" style={grid}>
        <span />
        {profs.map((p) => (
          <div key={p.identity.slug} className="cmp-head">
            <button
              className="cmp-drop"
              type="button"
              onClick={() => setDropped((d) => [...d, p.identity.slug])}
              aria-label={`Remove ${p.identity.name}`}
              title={`Remove ${p.identity.name}`}
            >
              ✕
            </button>
            {p.identity.imageUrl ? (
              <img className="cmp-face" src={p.identity.imageUrl} alt="" />
            ) : (
              <div className="cmp-face" aria-hidden="true" />
            )}
            <b>{p.identity.name}</b>
            <span>{p.identity.department ?? '—'}</span>
          </div>
        ))}
      </div>

      <div className="cmp-table">
        {rows.map((row) => (
          <div key={row.label} className="cmp-row" style={grid}>
            <div className="cmp-label">{row.label}</div>
            {row.values.map((v, i) => (
              <div
                key={profs[i].identity.slug}
                className={row.winners.includes(i) ? 'cmp-cell win' : 'cmp-cell'}
                title={
                  profs[i].summary.numRatings < MIN_RATINGS
                    ? `Under ${MIN_RATINGS} ratings — not enough to call a winner`
                    : undefined
                }
              >
                {row.label === 'Overall Rating' && v != null && (
                  <StarRating rating={v} size="sm" />
                )}
                {v == null ? '—' : row.format(v)}
              </div>
            ))}
          </div>
        ))}
      </div>

      <button className="cmp-add" type="button" disabled title="Needs the search screen">
        + Add Another Professor
      </button>
    </div>
  );
}
