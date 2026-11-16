import './Status.css';

/** Grey shapes where the screen's content will land, so it doesn't jump when
 *  the data arrives. `profile` is Overview's hero, score and tiles; `list` is
 *  rows, for Reviews, Courses and Compare. */
export function Loading({ shape = 'list' }: { shape?: 'profile' | 'list' }) {
  return (
    <div className="skel" role="status" aria-label="Loading">
      {shape === 'profile' ? (
        <>
          <div className="skel-hero">
            <span className="skel-block skel-avatar" />
            <span className="skel-lines">
              <span className="skel-block" style={{ width: '70%', height: 16 }} />
              <span className="skel-block" style={{ width: '45%' }} />
              <span className="skel-block" style={{ width: '38%', height: 18, borderRadius: 999 }} />
            </span>
          </div>
          <span className="skel-block" style={{ width: '50%', height: 26 }} />
          <div className="skel-pair">
            <span className="skel-block" style={{ height: 38 }} />
            <span className="skel-block" style={{ height: 38 }} />
          </div>
          <span className="skel-block" style={{ height: 70, borderRadius: 14 }} />
        </>
      ) : (
        [0, 1, 2, 3].map((i) => (
          <span key={i} className="skel-block" style={{ height: 54, borderRadius: 12 }} />
        ))
      )}
    </div>
  );
}

/** The sentence from errorMessage, and a way to try again without closing
 *  and reopening the popup. */
export function Failed({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="failed" role="alert">
      <p className="muted">{message}</p>
      <button className="btn secondary" type="button" onClick={onRetry}>
        Try again
      </button>
    </div>
  );
}
