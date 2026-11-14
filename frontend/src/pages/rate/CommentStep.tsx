import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { StepFoot } from './ChoiceGroup';
import { COMMENT_MAX, commentCountLabel } from './rateFlow';

// Measuring collapses the box for a moment, which can pull a page scrolled to the bottom up, so the scroll is put back.
function fit(t: HTMLTextAreaElement) {
  const y = window.scrollY;
  t.style.height = 'auto';
  t.style.height = `${t.scrollHeight + t.offsetHeight - t.clientHeight}px`;
  if (window.scrollY !== y) window.scrollTo(0, y);
}

interface CommentStepProps {
  value: string;
  onChange: (v: string) => void;
  onSubmit: (skip: boolean, honeypot: string) => void;
  onBack: () => void;
  submitting: boolean;
  // Narrower than submitting: false while the submit only waits on Cloudflare's click box.
  editLocked: boolean;
  updating: boolean;
  error: string;
  turnstileRef: (el: HTMLDivElement | null) => void;
  verifying: boolean;
  // Cloudflare's box is on screen: asking for a click, or showing that the check failed.
  boxShown: boolean;
  // The error says Cloudflare's check failed, so it shows with the check, not under the comment.
  errorAtCheck: boolean;
}

export function CommentStep({ value, onChange, onSubmit, onBack, submitting, editLocked, updating, error, turnstileRef, verifying, boxShown, errorAtCheck }: CommentStepProps) {
  const [honeypot, setHoneypot] = useState('');
  const checkError = errorAtCheck ? error : '';
  const ref = useRef<HTMLTextAreaElement>(null);
  const countId = useId();
  const count = commentCountLabel(value.length);

  // Grows with the text; the CSS max-height caps it and the box scrolls inside past that.
  useLayoutEffect(() => {
    if (ref.current) fit(ref.current);
  }, [value]);

  // A wider or narrower column rewraps the text, so refit on width changes too.
  useEffect(() => {
    const t = ref.current;
    if (!t) return;
    let width = t.clientWidth;
    const observer = new ResizeObserver(() => {
      if (t.clientWidth === width) return;
      width = t.clientWidth;
      fit(t);
    });
    observer.observe(t);
    return () => observer.disconnect();
  }, []);

  return (
    <>
      <h1 className="rate-q" tabIndex={-1}>Anything other students should know?</h1>
      <p className="rate-sub">Optional. Tips, how exams felt, what to expect.</p>
      <textarea
        ref={ref}
        className="rate-input rate-textarea"
        aria-label="Anything other students should know?"
        maxLength={COMMENT_MAX}
        aria-describedby={count ? countId : undefined}
        rows={5}
        placeholder="Optional"
        value={value}
        readOnly={editLocked}
        onChange={(e) => onChange(e.target.value)}
      />
      {count && <p className={`rate-count${value.length >= COMMENT_MAX ? ' is-out' : ''}`} id={countId}>{count}</p>}
      <input
        type="text"
        name="website"
        className="rate-hp"
        tabIndex={-1}
        autoComplete="off"
        aria-hidden="true"
        value={honeypot}
        onChange={(e) => setHoneypot(e.target.value)}
      />
      {error && !checkError && <p className="rate-error" role="alert">{error}</p>}
      <StepFoot onBack={onBack} backDisabled={editLocked}>
        {/* Empty unless Cloudflare shows its box or its check failed; then it sits right above Submit,
            pinned with it on desktop. Placed by the error's kind, not the box: a reset hides the box for a
            moment, and the error would jump away and back. */}
        <div className={`rate-verify${boxShown ? ' is-on' : ''}${checkError ? ' has-error' : ''}`}>
          {checkError && <p className="rate-error" role="alert">{checkError}</p>}
          {/* Always in the page, so screen readers announce the text when it's filled in. */}
          <p className="rate-verify-lead" role="status">{verifying ? 'One quick check before we send your rating.' : ''}</p>
          <div ref={turnstileRef} className="rate-turnstile" />
        </div>
        <button type="button" className="rate-btn" disabled={submitting} onClick={() => onSubmit(false, honeypot)}>
          {submitting ? (verifying ? 'Waiting for the check…' : 'Sending…') : updating ? 'Update rating' : 'Submit rating'}
        </button>
        {!updating && (
          <button type="button" className="rate-ghost" disabled={submitting} onClick={() => onSubmit(true, honeypot)}>
            {value.trim() ? 'Submit without comment' : 'Skip and submit'}
          </button>
        )}
      </StepFoot>
    </>
  );
}
