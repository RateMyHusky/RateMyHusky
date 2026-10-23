import { useEffect, useState } from 'react';
import { fetchProfessor, isUnavailable, isNotFound, professorUrl, type Professor } from '../api';
import StarRating from '../components/StarRating';
import StatTile from '../components/StatTile';
import AwardChips from '../components/AwardChips';
import { ScaleIcon, ReviewsIcon, InfoIcon } from '../components/icons';
import { score, percent, plural } from '../utils/format';
import './Overview.css';

type State =
  | { status: 'loading' }
  | { status: 'ready'; prof: Professor }
  | { status: 'error'; message: string };

export default function Overview({ slug, onCompare }: { slug: string; onCompare?: () => void }) {
  const [state, setState] = useState<State>({ status: 'loading' });

  useEffect(() => {
    let live = true;
    // Without this a slug change keeps the previous professor — name, scores
    // and View Reviews link — on screen until the new fetch resolves.
    setState({ status: 'loading' });
    fetchProfessor(slug)
      .then((prof) => live && setState({ status: 'ready', prof }))
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
  }, [slug]);

  if (state.status === 'loading') return <p className="muted">Loading…</p>;
  if (state.status === 'error') return <p className="muted">{state.message}</p>;

  const { identity, summary, courses, lastTaught, awards } = state.prof;

  return (
    <>
      <div className="hero">
        {identity.imageUrl ? (
          <img
            className="avatar"
            src={identity.imageUrl}
            alt=""
            style={{ objectPosition: `${identity.focusX}% ${identity.focusY}%` }}
          />
        ) : (
          <div className="avatar" aria-hidden="true" />
        )}
        <div className="who">
          <h1 className="name">{identity.name}</h1>
          {identity.department && <p className="dept">{identity.department}</p>}
          {lastTaught && <span className="chip">Last taught {lastTaught}</span>}
          <AwardChips awards={awards} moreHref={professorUrl(identity.slug)} />
        </div>
      </div>

      <div className="score">
        <div className="score-row">
          {/* No stars at all when there's no rating. Passing 0 drew five empty
              ones, which reads as "rated 0/5" right next to a dash saying
              there's nothing to show. */}
          {summary.rating != null && <StarRating rating={summary.rating} size="lg" />}
          <strong>{score(summary.rating)}</strong>
          <span className="outof">/ 5</span>
        </div>
        <p className="score-sub">
          from {summary.numRatings} {plural(summary.numRatings, 'rating')}
        </p>
      </div>

      <div className="actions">
        <button className="btn primary" type="button" onClick={onCompare} disabled={!onCompare}>
          <ScaleIcon />
          Compare
        </button>
        {/* A real link, not chrome.tabs.create: works in the popup, in any
            preview, and gives middle/cmd-click for free. */}
        <a
          className="btn secondary"
          href={professorUrl(identity.slug)}
          target="_blank"
          rel="noopener noreferrer"
        >
          <ReviewsIcon />
          View Reviews
        </a>
      </div>

      <p className="section-label">
        Key Stats
        <span className="info-wrap" title="From RateMyProfessors ratings, and courses from Banner.">
          <InfoIcon className="info" />
        </span>
      </p>
      <div className="tiles">
        <StatTile value={score(summary.difficulty)} label="Difficulty" />
        <StatTile value={percent(summary.wouldTakeAgainPct)} label="Take Again" />
        {/* Labelled all-time on purpose: this counts every course on record,
            and plenty of them were last taught years ago. Sitting unlabelled
            beside Difficulty and Take Again, it read as a current load. */}
        <StatTile value={String(courses.length)} label="All-Time Courses" />
      </div>
    </>
  );
}
