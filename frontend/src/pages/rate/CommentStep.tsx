import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { StepFoot } from './ChoiceGroup';

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
  updating: boolean;
  error: string;
  turnstileRef: (el: HTMLDivElement | null) => void;
  verifying: boolean;
}

export function CommentStep({ value, onChange, onSubmit, onBack, submitting, updating, error, turnstileRef, verifying }: CommentStepProps) {
  const [honeypot, setHoneypot] = useState('');
  const ref = useRef<HTMLTextAreaElement>(null);

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
        maxLength={2000}
        rows={5}
        placeholder="Optional"
        value={value}
        readOnly={submitting}
        onChange={(e) => onChange(e.target.value)}
      />
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
      {error && <p className="rate-error" role="alert">{error}</p>}
      <StepFoot onBack={onBack} backDisabled={submitting}>
        {/* Empty unless Cloudflare needs a click; then the box shows right above Submit, pinned with it on desktop. */}
        <div className={`rate-verify${verifying ? ' is-on' : ''}`}>
          {verifying && <p className="rate-verify-lead" role="status">One quick check before we send your rating.</p>}
          <div ref={turnstileRef} className="rate-turnstile" />
        </div>
        <button type="button" className="rate-btn" disabled={submitting} onClick={() => onSubmit(false, honeypot)}>
          {submitting ? 'Sending…' : updating ? 'Update rating' : 'Submit rating'}
        </button>
        {!updating && (
          <button type="button" className="rate-ghost" disabled={submitting} onClick={() => onSubmit(true, honeypot)}>
            Skip and submit
          </button>
        )}
      </StepFoot>
    </>
  );
}
