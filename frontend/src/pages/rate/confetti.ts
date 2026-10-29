// Confetti physics and canvas loop for the thanks screen. No React, no imports from api.ts.
export type PieceKind = 'paper' | 'dot' | 'ribbon';

export interface Piece {
  x: number; y: number; vx: number; vy: number; kind: PieceKind; w: number; h: number;
  rot: number; vr: number; flip: number; vflip: number; sway: number; vsway: number;
  drag: number; color: string;
}

export const CONFETTI_COLORS = ['#d6394c', '#e06070', '#1a9850', '#66bd63', '#f39c12', '#e67e22',
  '#3b82f6', '#a855f7', '#facc15', '#ffffff'];
export const CONFETTI_MS = 11000;
const MIN_MS = 2600;
const STEP_MS = 1000 / 60;
const MAX_FRAME_MS = 100;

const clamp = (v: number, lo: number, hi: number) => Math.max(Math.min(v, hi), lo);

// Sizes the pieces.
export const pieceScale = (width: number) => clamp(width / 1000, .75, 1.4);
// Sets launch speed, so a narrow phone isn't overshot.
export const launchScale = (width: number) => clamp(width / 1000, .38, 1.4);
export const confettiCount = (width: number) => Math.round(520 * Math.min(pieceScale(width), 1));

// aimDeg is in screen degrees (0 = right, -90 = straight up).
export function spawn(
  n: number, origin: { x: number; y: number }, aimDeg: number, width: number,
  rand: () => number = Math.random,
): Piece[] {
  const s = pieceScale(width), sp = launchScale(width), dir = aimDeg * Math.PI / 180;
  const pieces: Piece[] = [];
  for (let i = 0; i < n; i++) {
    const a = dir + (rand() - .5) * 2.3, v = (8 + rand() * 24) * sp, kind = rand();
    pieces.push({
      x: origin.x, y: origin.y, vx: Math.cos(a) * v, vy: Math.sin(a) * v,
      kind: kind < .12 ? 'ribbon' : kind < .3 ? 'dot' : 'paper',
      w: (5 + rand() * 5) * s, h: (8 + rand() * 7) * s,
      rot: rand() * 6.28, vr: (rand() - .5) * .3,
      flip: rand() * 6.28, vflip: .08 + rand() * .18,
      sway: rand() * 6.28, vsway: .03 + rand() * .05,
      drag: .962 + rand() * .016, color: CONFETTI_COLORS[(rand() * CONFETTI_COLORS.length) | 0],
    });
  }
  return pieces;
}

// Air drag stops the burst fast; paper then falls slowly, drifting side to side as it flips.
export function step(p: Piece, s: number): void {
  p.vx *= p.drag;
  p.vy = p.vy * p.drag + .22 * s;
  const term = (p.kind === 'dot' ? 3.2 : 2.2) * s;
  if (p.vy > term) p.vy = term;
  p.sway += p.vsway;
  p.flip += p.vflip;
  p.rot += p.vr * (p.vy > 0 ? .6 : 1);
  p.x += p.vx + (p.vy > 0 ? Math.sin(p.sway) * .9 * s : 0);
  p.y += p.vy;
}

export const alive = (p: Piece, w: number, h: number) => p.y < h + 30 && p.x > -60 && p.x < w + 60;

function draw(ctx: CanvasRenderingContext2D, p: Piece, s: number): void {
  ctx.save();
  ctx.translate(p.x, p.y);
  ctx.fillStyle = p.color;
  ctx.strokeStyle = p.color;
  if (p.kind === 'dot') {
    ctx.beginPath();
    ctx.ellipse(0, 0, p.w * .45, p.w * .45 * Math.abs(Math.cos(p.flip)) + .5, p.rot, 0, 6.28);
    ctx.fill();
  } else if (p.kind === 'ribbon') {
    ctx.rotate(p.rot);
    ctx.lineWidth = 2.2 * s;
    ctx.beginPath();
    for (let k = 0; k <= 10; k++) {
      const yy = (k - 5) * 2.4 * s, xx = Math.sin(k * .9 + p.flip) * 3.5 * s;
      if (k) ctx.lineTo(xx, yy); else ctx.moveTo(xx, yy);
    }
    ctx.stroke();
  } else {
    ctx.rotate(p.rot);
    ctx.scale(1, Math.cos(p.flip));
    ctx.globalAlpha = Math.cos(p.flip) > 0 ? 1 : .75;
    ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
  }
  ctx.restore();
}

// The caller has already appended the canvas. Returns cancel, which stops the loop and removes it.
// Physics run at a fixed 60 Hz however fast the screen refreshes.
export function runConfetti(canvas: HTMLCanvasElement, pieces: Piece[], s: number): () => void {
  const dpr = window.devicePixelRatio || 1;
  let W = 0, H = 0;
  const ctx = canvas.getContext('2d');
  if (!ctx) {
    canvas.remove();
    return () => {};
  }
  // Sizes the backing store from the displayed size, so a classic scrollbar doesn't squeeze the drawing.
  const fit = () => {
    W = canvas.clientWidth;
    H = canvas.clientHeight;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  };
  fit();
  let live = pieces, frame = 0, last = performance.now(), acc = 0;
  const start = last;
  const stop = () => {
    cancelAnimationFrame(frame);
    canvas.remove();
  };
  const tick = (now: number) => {
    if (canvas.clientWidth !== W || canvas.clientHeight !== H) fit();
    acc += clamp(now - last, 0, MAX_FRAME_MS);
    last = now;
    for (; acc >= STEP_MS; acc -= STEP_MS) {
      live.forEach((p) => step(p, s));
      live = live.filter((p) => alive(p, W, H));
    }
    ctx.clearRect(0, 0, W, H);
    live.forEach((p) => draw(ctx, p, s));
    if (now - start < CONFETTI_MS && (live.length || now - start < MIN_MS)) frame = requestAnimationFrame(tick);
    else stop();
  };
  frame = requestAnimationFrame(tick);
  return stop;
}
