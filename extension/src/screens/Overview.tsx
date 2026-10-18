import { useEffect, useState } from 'react';
import { fetchProfessor, isUnavailable, professorUrl, type Professor } from '../api';
import StarRating from '../components/StarRating';
import StatTile from '../components/StatTile';
import { ScaleIcon, ReviewsIcon, InfoIcon } from '../components/icons';
import { score, percent, plural } from '../utils/format';
import './Overview.css';

type State =
  | { status: 'loading' }
  | { status: 'ready'; prof: Professor }
  | { status: 'error'; message: string };

export default function Overview({ slug }: { slug: string }) {
  const [state, setState] = useState<State>({ status: 'loading' });

  useEffect(() => {
    let live = true;
    fetchProfessor(slug)
      .then((prof) => live && setState({ status: 'ready', prof }))
      .catch((err) =>
        live &&
        setState({
          status: 'error',
          message: isUnavailable(err)
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

  const { identity, summary, courses, lastTaught, redditMentions } = state.prof;

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
        </div>
      </div>

      {/* Angela's two-source split. The right column was TRACE; Reddit is the
          other source we actually have. */}
      <div className="scores">
        <div className="score">
          <div className="score-row">
            <StarRating rating={summary.rating ?? 0} size="md" />
            <strong>{score(summary.rating)}</strong>
            <span className="outof">/ 5</span>
          </div>
          <p className="score-sub">from {summary.numRatings} reviews</p>
        </div>

        <div className="score">
          <p className="score-label">REDDIT</p>
          <div className="score-row">
            <strong>{redditMentions.length}</strong>
          </div>
          <p className="score-sub">
            {plural(redditMentions.length, 'mention')} on r/NEU
          </p>
        </div>
      </div>

      <div className="actions">
        <button className="btn primary" type="button" disabled title="Coming soon">
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
        <InfoIcon className="info" />
      </p>
      <div className="tiles">
        <StatTile value={score(summary.difficulty)} label="Difficulty" />
        <StatTile value={percent(summary.wouldTakeAgainPct)} label="Take Again" />
        <StatTile value={String(courses.length)} label="Courses" />
      </div>
    </>
  );
}
