import { useState } from 'react';
import { fetchProfessor, professorUrl, type Review } from '../api';
import StarRating from '../components/StarRating';
import { plural } from '../utils/format';
import { useAsync } from '../utils/useAsync';
import './Reviews.css';

type Sort = 'newest' | 'highest' | 'lowest';

const SORTS: { value: Sort; label: string }[] = [
  { value: 'newest', label: 'Newest' },
  { value: 'highest', label: 'Highest' },
  { value: 'lowest', label: 'Lowest' },
];

function sortReviews(reviews: Review[], sort: Sort): Review[] {
  const out = [...reviews];
  if (sort === 'highest') return out.sort((a, b) => b.quality - a.quality);
  if (sort === 'lowest') return out.sort((a, b) => a.quality - b.quality);
  return out.sort((a, b) => (Date.parse(b.date) || 0) - (Date.parse(a.date) || 0));
}

function monthYear(value: string): string {
  const d = new Date(value);
  return Number.isNaN(d.getTime())
    ? value
    : d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
}

/** Older reviews have no id, and two can be word-for-word the same, so the
 *  key falls back to the content plus how many times it's been seen. */
function keyed(reviews: Review[]): { review: Review; key: string }[] {
  const seen = new Map<string, number>();
  return reviews.map((review) => {
    const base =
      review.id != null
        ? String(review.id)
        : JSON.stringify([review.date, review.courseCode, review.quality, review.comment]);
    const n = seen.get(base) ?? 0;
    seen.set(base, n + 1);
    return { review, key: `${base}-${n}` };
  });
}

export default function Reviews({ slug }: { slug: string }) {
  const state = useAsync(() => fetchProfessor(slug), slug);
  const [sort, setSort] = useState<Sort>('newest');

  if (state.status === 'loading') return <p className="muted">Loading…</p>;
  if (state.status === 'error') return <p className="muted">{state.message}</p>;

  const { identity, sources } = state.data;
  const reviews = sources.rmp.reviews;

  return (
    <div className="reviews">
      <div className="rev-head">
        <p className="section-label">
          {identity.name} · {reviews.length} {plural(reviews.length, 'review')}
        </p>
        {reviews.length > 1 && (
          <div className="rev-sort" role="radiogroup" aria-label="Sort reviews">
            {SORTS.map((s) => (
              <label key={s.value} className={s.value === sort ? 'rev-sort-opt on' : 'rev-sort-opt'}>
                <input
                  type="radio"
                  name="review-sort"
                  value={s.value}
                  checked={s.value === sort}
                  onChange={() => setSort(s.value)}
                />
                {s.label}
              </label>
            ))}
          </div>
        )}
      </div>

      {reviews.length === 0 ? (
        <p className="muted">No reviews yet.</p>
      ) : (
        <ul className="rev-list">
          {keyed(sortReviews(reviews, sort)).map(({ review, key }) => {
            const tags = review.tags
              .split('--')
              .map((t) => t.trim())
              .filter(Boolean);
            return (
              <li key={key} className="rev">
                <div className="rev-top">
                  <StarRating rating={review.quality} size="sm" />
                  {review.courseCode && <span className="rev-course">{review.courseCode}</span>}
                  <span className="rev-date">{monthYear(review.date)}</span>
                </div>
                {review.comment ? (
                  <p className="rev-text">{review.comment}</p>
                ) : (
                  <p className="rev-text muted">No written comment.</p>
                )}
                <p className="rev-meta">Difficulty {review.difficulty}/5</p>
                {tags.length > 0 && (
                  <div className="rev-tags">
                    {tags.map((t) => (
                      <span key={t} className="rev-tag">
                        {t.toLowerCase()}
                      </span>
                    ))}
                  </div>
                )}
              </li>
            );
          })}
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
