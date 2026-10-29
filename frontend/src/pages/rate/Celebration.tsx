import { useEffect, useRef } from 'react';
import { PartyPopper, POPPER_REST_DEG } from './PartyPopper';
import type { PopperRefs } from './PartyPopper';
import { confettiCount, pieceScale, runConfetti, spawn } from './confetti';
import { useMediaQuery } from './useMediaQuery';

const UP_DEG = -90;
const FIRE_MS = 320;
const RETURN_MS = 900;
const MOBILE_LIFT_PX = 12;

// The party popper on the thanks screen: turns up, fires one confetti blast, then settles back.
export function Celebration(): React.JSX.Element {
  const refs = useRef<PopperRefs>({ aim: null, svg: null, mouth: null });
  const desktop = useMediaQuery('(min-width: 1024px)');
  const reduced = useMediaQuery('(prefers-reduced-motion: reduce)');
  // Decided once at mount, so a resize mid-blast doesn't restart it.
  const mode = useRef({ mobile: !desktop, reduced });

  useEffect(() => {
    const { aim, svg, mouth } = refs.current;
    if (mode.current.reduced || !aim || !svg || !mouth) return;
    const { mobile } = mode.current;
    // The cone turns around its tip, so pointing up puts the mouth straight above the tip.
    const rect = aim.getBoundingClientRect();
    const tipX = rect.left + rect.width * .09;
    const point = (deg: number) => {
      const shift = mobile && deg === UP_DEG ? window.innerWidth / 2 - tipX : 0;
      aim.style.transform = `translateX(${shift}px) rotate(${deg - POPPER_REST_DEG}deg)`;
    };
    let cancel = () => {};
    const fire = () => {
      const r = mouth.getBoundingClientRect();
      const origin = { x: r.left + r.width / 2, y: r.top + r.height / 2 - (mobile ? MOBILE_LIFT_PX : 0) };
      svg.classList.remove('kick');
      void svg.getBoundingClientRect();
      svg.classList.add('kick');
      const canvas = document.createElement('canvas');
      canvas.className = 'rate-confetti';
      canvas.setAttribute('aria-hidden', 'true');
      document.body.appendChild(canvas);
      const width = window.innerWidth;
      cancel = runConfetti(canvas, spawn(confettiCount(width), origin, UP_DEG, width), pieceScale(width));
    };
    point(UP_DEG);
    const timers = [setTimeout(fire, FIRE_MS), setTimeout(() => point(POPPER_REST_DEG), RETURN_MS)];
    return () => {
      timers.forEach(clearTimeout);
      cancel();
      aim.style.transform = '';
    };
  }, []);

  return (
    <div className="rate-popper">
      <PartyPopper refs={refs} size={desktop ? '6em' : '64px'} />
    </div>
  );
}
