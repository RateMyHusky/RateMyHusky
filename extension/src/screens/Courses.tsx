import { useEffect, useState } from 'react';
import { errorMessage, fetchProfessor, courseUrl, type Course, type Professor } from '../api';
import { termRank } from '../utils/terms';
import { plural } from '../utils/format';
import './Courses.css';

type State =
  | { status: 'loading' }
  | { status: 'ready'; prof: Professor }
  | { status: 'error'; message: string };

/** Most recently taught first; ties broken by code so the order is stable. */
function byRecency(a: Course, b: Course): number {
  return termRank(b.lastTerm) - termRank(a.lastTerm) || a.code.localeCompare(b.code);
}

export default function Courses({ slug }: { slug: string }) {
  const [state, setState] = useState<State>({ status: 'loading' });

  useEffect(() => {
    let live = true;
    setState({ status: 'loading' });
    fetchProfessor(slug)
      .then((prof) => live && setState({ status: 'ready', prof }))
      .catch((err) => live && setState({ status: 'error', message: errorMessage(err) }));
    return () => {
      live = false;
    };
  }, [slug]);

  if (state.status === 'loading') return <p className="muted">Loading…</p>;
  if (state.status === 'error') return <p className="muted">{state.message}</p>;

  const courses = [...state.prof.courses].sort(byRecency);
  if (courses.length === 0) return <p className="muted">No courses on record.</p>;

  return (
    <div className="courses">
      {/* "All courses", not "currently teaching": this is everything on record,
          and the oldest here go back several years. Matches the Overview tile. */}
      <p className="section-label">All Courses ({courses.length})</p>

      <ul className="crs-list">
        {courses.map((c) => {
          const meta = [
            `${c.terms.length} ${plural(c.terms.length, 'term')}`,
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
