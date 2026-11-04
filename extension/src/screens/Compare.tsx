import { errorMessage, fetchProfessor, safeHttpUrl, type Professor } from '../api';
import StarRating from '../components/StarRating';
import { buildRows, MIN_RATINGS } from '../utils/compare';
import { useAsync } from '../utils/useAsync';
import './Compare.css';

/** A slug that didn't load, kept beside the ones that did so the student can
 *  see which one to remove instead of losing the whole comparison. */
type Failed = { slug: string; message: string };

type Comparison = { profs: Professor[]; failed: Failed[] };

async function loadComparison(slugs: string[]): Promise<Comparison> {
  // allSettled, not all: one stale slug shouldn't throw away the professors
  // that loaded fine, and a blank screen doesn't say which one to drop.
  const results = await Promise.allSettled(slugs.map(fetchProfessor));
  const profs = results.flatMap((r) => (r.status === 'fulfilled' ? [r.value] : []));
  const failed = results.flatMap((r, i) =>
    r.status === 'rejected' ? [{ slug: slugs[i], message: errorMessage(r.reason) }] : [],
  );
  // Nothing loaded at all: the first failure becomes the screen's error.
  const first = results.find((r): r is PromiseRejectedResult => r.status === 'rejected');
  if (profs.length === 0 && first) throw first.reason;
  return { profs, failed };
}

export default function Compare({
  slugs,
  dropped,
  onDrop,
}: {
  slugs: string[];
  dropped: string[];
  onDrop: (slug: string) => void;
}) {
  const state = useAsync(() => loadComparison(slugs), slugs.join(','));

  if (state.status === 'loading') return <p className="muted">Loading…</p>;
  if (state.status === 'error') return <p className="muted">{state.message}</p>;

  const profs = state.data.profs.filter((p) => !dropped.includes(p.identity.slug));
  const failed = state.data.failed.filter((f) => !dropped.includes(f.slug));
  if (profs.length === 0) return <p className="muted">No professors to compare.</p>;

  const { rows, low } = buildRows(profs);
  const grid = { gridTemplateColumns: `76px repeat(${profs.length}, minmax(0, 1fr))` };

  return (
    <div className="compare">
      <div className="cmp-heads" style={grid}>
        {/* The blank cell over the row labels. The cards share the rows' grid
            or they stop sitting above their own numbers. */}
        <span aria-hidden="true" />
        {profs.map((p) => {
          const image = safeHttpUrl(p.identity.imageUrl);
          return (
            <div key={p.identity.slug} className="cmp-head">
              <button
                className="cmp-drop"
                type="button"
                onClick={() => onDrop(p.identity.slug)}
                aria-label={`Remove ${p.identity.name}`}
                title={`Remove ${p.identity.name}`}
              >
                ✕
              </button>
              {image ? (
                <img className="cmp-face" src={image} alt="" />
              ) : (
                <div className="cmp-face" aria-hidden="true" />
              )}
              <b>{p.identity.name}</b>
              <span>{p.identity.department ?? '—'}</span>
            </div>
          );
        })}
      </div>

      <div className="cmp-table">
        {rows.map((row) => (
          <div key={row.label} className="cmp-row" style={grid}>
            <div className="cmp-label">{row.label}</div>
            {row.values.map((v, i) => (
              <div
                key={profs[i].identity.slug}
                className={
                  low[i]
                    ? 'cmp-cell low'
                    : row.winners.includes(i)
                      ? 'cmp-cell win'
                      : 'cmp-cell'
                }
              >
                {row.stars && v != null && <StarRating rating={v} size="sm" />}
                {row.format(v)}
              </div>
            ))}
          </div>
        ))}
      </div>

      {/* On screen rather than in a cell's title: a tooltip on a hover-only
          cell is unreachable by keyboard and on touch, which left these
          columns looking like they lost every row. */}
      {low.some(Boolean) && (
        <p className="muted cmp-note">
          Greyed columns have fewer than {MIN_RATINGS} ratings and aren’t ranked.
        </p>
      )}

      {/* One line each, with its own ✕: a slug that failed has no card to
          remove it from. The reason is shown because it decides what to do —
          a 404 means drop it, an outage means try again later. */}
      {failed.map((f) => (
        <p key={f.slug} className="muted cmp-note cmp-failed">
          <span>
            {f.slug}: {f.message}
          </span>
          <button
            className="cmp-drop"
            type="button"
            onClick={() => onDrop(f.slug)}
            aria-label={`Dismiss ${f.slug}`}
            title={`Dismiss ${f.slug}`}
          >
            ✕
          </button>
        </p>
      ))}

      {/* The reason sits on screen rather than in a title: Chrome doesn't
          reliably fire tooltips on a disabled button, so a title here would
          leave the control looking broken for no stated reason. */}
      <button className="cmp-add" type="button" disabled>
        + Add Another Professor
      </button>
      <p className="muted cmp-add-note">Adding a professor needs the search screen.</p>
    </div>
  );
}
