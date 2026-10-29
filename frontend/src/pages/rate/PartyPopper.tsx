import type { RefObject } from 'react';

// Party popper: tip at (6,60), mouth is the ellipse centered at (34,30). At rest it points up-right.
export const POPPER_REST_DEG = Math.atan2(30 - 60, 34 - 6) * 180 / Math.PI;

export interface PopperRefs {
  aim: HTMLSpanElement | null;
  svg: SVGSVGElement | null;
  mouth: SVGEllipseElement | null;
}

const bind = <K extends keyof PopperRefs>(refs: RefObject<PopperRefs>, key: K) =>
  (el: PopperRefs[K]) => { refs.current[key] = el; };

// The outer span aims the cone (turns around its tip); the svg inside does the kick on each pop.
export function PartyPopper({ refs, size }: { refs: RefObject<PopperRefs>; size: string }): React.JSX.Element {
  return (
    <span className="rate-popper-aim" ref={bind(refs, 'aim')} aria-hidden="true">
      <svg viewBox="0 0 64 64" width={size} height={size} ref={bind(refs, 'svg')}>
        <defs>
          <linearGradient id="cg" x1="0" y1="1" x2="1" y2="0">
            <stop offset="0" stopColor="#f5b82e" />
            <stop offset="1" stopColor="#f7d36b" />
          </linearGradient>
        </defs>
        <path d="M6 60 L22 18 L46 42 Z" fill="url(#cg)" stroke="#c98a12" strokeWidth="1.5" strokeLinejoin="round" />
        <path d="M12 44 L30 51" stroke="#d6394c" strokeWidth="4" strokeLinecap="round" />
        <path d="M17 31 L39 39" stroke="#d6394c" strokeWidth="4" strokeLinecap="round" />
        <ellipse ref={bind(refs, 'mouth')} cx="34" cy="30" rx="17" ry="5.5"
          transform="rotate(45 34 30)" fill="#e9a71c" stroke="#c98a12" strokeWidth="1.5" />
      </svg>
    </span>
  );
}
