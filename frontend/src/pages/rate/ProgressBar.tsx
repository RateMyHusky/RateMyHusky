import { useLayoutEffect, useRef } from 'react';
import { QUESTION_COUNT } from './rateFlow';

/* The segments carry no React className: the layout effect toggles `on` itself so each fill can transition with a stagger. */
export function ProgressBar({ index, done }: { index: number; done: boolean }) {
  const barRef = useRef<HTMLDivElement>(null);
  const shown = useRef(-1);

  useLayoutEffect(() => {
    const bar = barRef.current;
    const from = shown.current;
    if (from === index || !bar) return;
    // Resolve the segments' current style so the change transitions, including on first mount (offsetWidth alone skips them there).
    bar.querySelectorAll('b').forEach((b) => void getComputedStyle(b).transform);
    // Thanks sits one past the last segment, so a drain from there starts at the last segment, without a beat's wait.
    const top = Math.min(from, QUESTION_COUNT - 1);
    Array.from(bar.children).forEach((seg, i) => {
      const on = i <= index;
      if (seg.classList.contains('on') === on) return;
      (seg as HTMLElement).style.setProperty('--d', `${(index > from ? i - from - 1 : top - i) * 70}ms`);
      seg.classList.toggle('on', on);
    });
    shown.current = index;
  }, [index]);

  return (
    <div ref={barRef} className={`rate-prog${done ? ' is-done' : ''}`} aria-hidden="true">
      {Array.from({ length: QUESTION_COUNT }, (_, i) => <i key={i}><b /></i>)}
    </div>
  );
}
