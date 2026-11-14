import { courseUrl, fetchProfessor, RECENT_TERMS_CAP } from '../api';
import { plural } from '../utils/format';
import { useAsync } from '../utils/useAsync';
import './Courses.css';

/** A full list means "at least this many", since Banner history stops at the
 *  cap. No terms at all means Banner has no record of the course, and printing
 *  "0 terms" there read as never taught. */
function termCount(n: number): string | null {
  if (n === 0) return null;
  return `${n}${n >= RECENT_TERMS_CAP ? '+' : ''} ${plural(n, 'term')}`;
}

export default function Courses({ slug }: { slug: string }) {
  const state = useAsync(() => fetchProfessor(slug), slug);

  if (state.status === 'loading') return <p className="muted">Loading…</p>;
  if (state.status === 'error') return <p className="muted">{state.message}</p>;

  // In the order /full sends them — taught courses most recent first, then
  // the rated-only ones most-rated first. Re-sorting here undid that, and got
  // Winter and the summer sessions wrong besides.
  const courses = state.data.courses;
  if (courses.length === 0) return <p className="muted">No courses on record.</p>;

  return (
    <div className="courses">
      {/* "All courses", not "currently teaching": this is everything on record,
          and the oldest here go back several years. Matches the Overview tile. */}
      <p className="section-label">All Courses ({courses.length})</p>

      <ul className="crs-list">
        {courses.map((c) => {
          const meta = [
            termCount(c.terms.length),
            c.lastTerm ? `last ${c.lastTerm}` : null,
            c.numRatings > 0 ? `${c.numRatings} ${plural(c.numRatings, 'rating')}` : null,
          ]
            .filter(Boolean)
            .join(' · ');

          const inner = (
            <>
              <span className="crs-code">{c.code}</span>
              <span className="crs-main">
                <span className="crs-title">{c.name ?? c.code}</span>
                <span className="crs-meta">{meta}</span>
              </span>
            </>
          );

          // Only the courses with a page on the site are worth linking; the
          // rest would land on a 404, so they stay plain text.
          return (
            <li key={c.code} className="crs">
              {c.hasPage ? (
                <a
                  className="crs-link"
                  href={courseUrl(c.code)}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {inner}
                  <span className="crs-chev" aria-hidden="true">›</span>
                </a>
              ) : (
                <span className="crs-link plain">{inner}</span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
