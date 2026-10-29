import { useLayoutEffect, useRef } from 'react';

/**
 * One line of text that shrinks (never grows) to fit its parent's width. The parent keeps its
 * own font-size and line-height, so its height doesn't change with the text.
 */
export default function FitText({ children }: { children: string }) {
  const ref = useRef<HTMLSpanElement>(null);

  useLayoutEffect(() => {
    const span = ref.current!;
    const box = span.parentElement!;
    const fit = () => {
      span.style.fontSize = '';
      const ratio = box.clientWidth / span.offsetWidth;
      if (ratio < 1) span.style.fontSize = `${ratio}em`;
    };
    fit();
    // The width changes with the window, and again once the web font replaces the fallback.
    const observer = new ResizeObserver(fit);
    observer.observe(box);
    document.fonts.ready.then(fit);
    return () => observer.disconnect();
  }, [children]);

  return <span ref={ref} style={{ display: 'inline-block', whiteSpace: 'nowrap' }}>{children}</span>;
}
