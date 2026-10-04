import './LoadError.css';

/* Shown when a page's data failed for any reason other than a 404 (which shows NotFound). */
const LoadError = () => (
  <div className="load-error" role="alert">
    <p className="load-error-title">Something went wrong — try again.</p>
    <button type="button" className="load-error-retry" onClick={() => window.location.reload()}>
      Try again
    </button>
  </div>
);

export default LoadError;
