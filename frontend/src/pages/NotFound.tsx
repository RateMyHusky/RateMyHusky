import { Link } from 'react-router-dom';
import Footer from '../components/Footer';

import huskyIcon from '../assets/neu-husky-icon.png';
import './NotFound.css';

interface NotFoundProps {
  /** A dead professor or course link: say so, and point at that catalog. */
  kind?: 'professor' | 'course';
}

const COPY = {
  professor: {
    title: "We can't find that professor.",
    body: 'They may have left Northeastern, or the link has a typo. Browse the professor catalog to find them.',
    catalog: '/professors', browse: 'Browse professors',
  },
  course: {
    title: "We don't have that course.",
    body: 'It may have been renumbered, or the link has a typo. Browse the course catalog to find it.',
    catalog: '/courses', browse: 'Browse courses',
  },
} as const;

const NotFound = ({ kind }: NotFoundProps) => {
  const copy = kind ? COPY[kind] : null;

  return (
    <div className="not-found-page">
      <title>Not found | RateMyHusky</title>
      <meta name="robots" content="noindex" />
      <main className="not-found-main">
        <div className="not-found-shell">
          <section className="not-found-hero">
            <div className="not-found-copy">
              <h1>{copy ? copy.title : 'That page is off the map.'}</h1>
              <p>
                {copy ? copy.body : 'The link you followed does not point to an active page. Head back to the homepage or browse the professor catalog to get back on track.'}
              </p>

              <div className="not-found-actions">
                <Link to="/" className="not-found-primary-btn">
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
