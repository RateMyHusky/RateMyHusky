import { fetchProfessor, professorUrl, rateUrl, safeHttpUrl } from '../api';
import StarRating from '../components/StarRating';
import StatTile from '../components/StatTile';
import AwardChips from '../components/AwardChips';
import { ScaleIcon, ReviewsIcon, InfoIcon, BookmarkIcon } from '../components/icons';
import { useSaved } from '../components/SavedList';
import { save, unsave } from '../utils/saved';
import { score, percent, plural } from '../utils/format';
import { useAsync } from '../utils/useAsync';
import { Failed, Loading } from '../components/Status';
import './Overview.css';

export default function Overview({
  slug,
  onCompare,
  onReviews,
  onCourses,
}: {
  slug: string;
  onCompare?: () => void;
  onReviews?: () => void;
  onCourses?: () => void;
}) {
  const state = useAsync(() => fetchProfessor(slug), slug);
  const saved = useSaved().some((s) => s.slug === slug);
  // chrome.storage is missing outside the extension, so there's nowhere to save.
  const canSave = typeof chrome !== 'undefined' && !!chrome.storage;

  if (state.status === 'loading') return <Loading shape="profile" />;
  if (state.status === 'error') return <Failed message={state.message} onRetry={state.retry} />;

  const { identity, summary, courses, lastTaught, awards } = state.data;
  const image = safeHttpUrl(identity.imageUrl);

  return (
    <>
      <div className="hero">
        {image ? (
          <img
            className="avatar"
            src={image}
            alt=""
            style={{ objectPosition: `${identity.focusX}% ${identity.focusY}%` }}
          />
        ) : (
          <div className="avatar" aria-hidden="true" />
        )}
        <div className="who">
          <h1 className="name">{identity.name}</h1>
          <button
            className={saved ? 'save-btn on' : 'save-btn'}
            type="button"
            disabled={!canSave}
            aria-pressed={saved}
            aria-label={saved ? `Remove ${identity.name} from saved` : `Save ${identity.name}`}
            title={saved ? 'Saved' : 'Save'}
            onClick={() => void (saved ? unsave(slug) : save(slug, identity.name))}
          >
            <BookmarkIcon filled={saved} />
          </button>
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
        {/* In the popup, not a link out: the reviews are already in the /full
            payload this screen loaded. Reviews links to the site at its foot. */}
        <button className="btn secondary" type="button" onClick={onReviews} disabled={!onReviews}>
          <ReviewsIcon />
          View Reviews
        </button>
      </div>
      {/* Read, then add one: the popup otherwise only ever takes. A link, not
          a third button, so it doesn't compete with the two above. */}
      <a className="rate-link" href={rateUrl(identity.slug)} target="_blank" rel="noopener noreferrer">
        Taken their class? Rate this professor
      </a>

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
        <StatTile value={String(courses.length)} label="All-Time Courses" onClick={onCourses} />
      </div>
    </>
  );
}
