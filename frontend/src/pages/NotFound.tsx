import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import Footer from '../components/Footer';

import huskyIcon from '../assets/neu-husky-icon.png';
import './NotFound.css';

interface NotFoundProps {
  /** A dead professor or course link: say so, and search that catalog for what the URL named. */
  kind?: 'professor' | 'course';
  /** What the URL named (a slug's words, a course code), to start the search with. */
  query?: string;
}

const COPY = {
  professor: {
    title: "We can't find that professor.",
    body: 'They may have left Northeastern, or the link has a typo. Search the professor catalog by name.',
    catalog: '/professors', browse: 'Browse professors', placeholder: 'Professor name',
  },
  course: {
    title: "We don't have that course.",
    body: 'It may have been renumbered, or the link has a typo. Search the course catalog by code or title.',
    catalog: '/courses', browse: 'Browse courses', placeholder: 'Course code or title',
  },
} as const;

const NotFound = ({ kind, query = '' }: NotFoundProps) => {
  const navigate = useNavigate();
  const [q, setQ] = useState(query);
  const copy = kind ? COPY[kind] : null;

  return (
    <div className="not-found-page">
      <main className="not-found-main">
        <div className="not-found-shell">
          <section className="not-found-hero">
            <div className="not-found-copy">
              <h1>{copy ? copy.title : 'That page is off the map.'}</h1>
              <p>
                {copy ? copy.body : 'The link you followed does not point to an active page. Head back to the homepage or browse the professor catalog to get back on track.'}
              </p>

              {copy && (
                <form
                  className="not-found-search"
                  role="search"
                  onSubmit={(e) => {
                    e.preventDefault();
                    navigate(q.trim() ? `${copy.catalog}?q=${encodeURIComponent(q.trim())}` : copy.catalog);
                  }}
                >
                  <input
                    type="search"
                    value={q}
                    onChange={(e) => setQ(e.target.value)}
                    placeholder={copy.placeholder}
                    aria-label={copy.placeholder}
                  />
                  <button type="submit" className="not-found-primary-btn">Search</button>
                </form>
              )}

              <div className="not-found-actions">
                <Link to="/" className={copy ? 'not-found-secondary-btn' : 'not-found-primary-btn'}>
                  Back to homepage
                </Link>
                <Link to={copy ? copy.catalog : '/professors'} className="not-found-secondary-btn">
                  {copy ? copy.browse : 'Browse professors'}
                </Link>
              </div>
            </div>

            <div className="not-found-visual" aria-hidden="true">
              <div className="not-found-visual-glow" />
              <div className="not-found-visual-card">
                <img src={huskyIcon} alt="" className="not-found-husky" />
              </div>
            </div>
          </section>
        </div>
      </main>
      <Footer />
    </div>
  );
};

export default NotFound;
