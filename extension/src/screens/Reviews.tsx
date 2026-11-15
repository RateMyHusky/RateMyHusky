import { useState } from 'react';
import { fetchProfessor, professorUrl } from '../api';
import StarRating from '../components/StarRating';
import { plural } from '../utils/format';
import { mergeReviews, sortReviews, type Sort, type Source } from '../utils/reviews';
import { useAsync } from '../utils/useAsync';
import { Failed, Loading } from '../components/Status';
import './Reviews.css';

const SORTS: { value: Sort; label: string }[] = [
  { value: 'newest', label: 'Newest' },
  { value: 'highest', label: 'Highest' },
  { value: 'lowest', label: 'Lowest' },
];

type Filter = 'all' | Source;

const FILTERS: { value: Filter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'rmh', label: 'RateMyHusky' },
  { value: 'rmp', label: 'RateMyProfessors' },
];

const SOURCE_LABEL: Record<Source, string> = { rmh: 'RateMyHusky', rmp: 'RateMyProfessors' };

/** A row of Settings' segmented control, scaled down. Real radios, so the
 *  arrow keys and the "1 of 3" announcement come from the browser. */
function Segmented<T extends string>({
  name,
  label,
  options,
  value,
  onChange,
}: {
  name: string;
  label: string;
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="rev-seg" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <label key={o.value} className={o.value === value ? 'rev-seg-opt on' : 'rev-seg-opt'}>
          <input
            type="radio"
            name={name}
            value={o.value}
            checked={o.value === value}
            onChange={() => onChange(o.value)}
          />
          {o.label}
        </label>
      ))}
    </div>
  );
}

export default function Reviews({ slug }: { slug: string }) {
  const state = useAsync(() => fetchProfessor(slug), slug);
  const [sort, setSort] = useState<Sort>('newest');
  const [filter, setFilter] = useState<Filter>('all');

  if (state.status === 'loading') return <Loading />;
  if (state.status === 'error') return <Failed message={state.message} onRetry={state.retry} />;

  const { identity, sources } = state.data;
  const all = mergeReviews(sources.rmp.reviews, sources.survey?.reviews ?? []);
  // Written RateMyHusky reviews the site only shows signed-in students. The
  // popup can't sign in, so it says they exist and where to read them, rather
  // than leaving students to think a professor has none.
  const locked = sources.survey?.lockedReviews ?? 0;
  // The source filter only earns its row once there's something to choose
  // between; most professors have no RateMyHusky reviews yet.
  const mixed = all.some((r) => r.source === 'rmh') && all.some((r) => r.source === 'rmp');
  const shown = sortReviews(
    mixed && filter !== 'all' ? all.filter((r) => r.source === filter) : all,
    sort,
  );

  return (
    <div className="reviews">
      <div className="rev-head">
        <p className="section-label">
          {identity.name} · {all.length} {plural(all.length, 'review')}
        </p>
        {mixed && (
          <Segmented
            name="review-source"
            label="Show reviews from"
            options={FILTERS}
            value={filter}
            onChange={setFilter}
          />
        )}
        {shown.length > 1 && (
          <Segmented
            name="review-sort"
            label="Sort reviews"
            options={SORTS}
            value={sort}
            onChange={setSort}
          />
        )}
      </div>

      {locked > 0 && (
        <a
          className="rev-locked"
          href={professorUrl(identity.slug)}
          target="_blank"
          rel="noopener noreferrer"
        >
          {locked} more {plural(locked, 'review')} from Northeastern students on RateMyHusky — sign
          in on the site to read {locked === 1 ? 'it' : 'them'}
        </a>
      )}

      {shown.length === 0 ? (
        <p className="muted">{locked > 0 ? 'No other reviews yet.' : 'No reviews yet.'}</p>
      ) : (
        <ul className="rev-list">
          {shown.map((r) => (
            <li key={r.key} className="rev">
              <div className="rev-top">
                <StarRating rating={r.rating} size="sm" />
                {r.course && <span className="rev-course">{r.course}</span>}
                {r.when && <span className="rev-date">{r.when}</span>}
              </div>
              {r.comment ? (
                <p className="rev-text">{r.comment}</p>
              ) : (
                <p className="rev-text muted">No written comment.</p>
              )}
              <p className="rev-meta">
                <span className={r.source === 'rmh' ? 'rev-src rmh' : 'rev-src'}>
                  {SOURCE_LABEL[r.source]}
                </span>
                {r.difficulty != null && <span>Difficulty {r.difficulty}/5</span>}
              </p>
              {r.tags.length > 0 && (
                <div className="rev-tags">
                  {r.tags.map((t) => (
                    <span key={t} className="rev-tag">
                      {t}
                    </span>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      <a
        className="btn secondary rev-more"
        href={professorUrl(identity.slug)}
        target="_blank"
        rel="noopener noreferrer"
      >
        See everything on RateMyHusky
      </a>
    </div>
  );
}
