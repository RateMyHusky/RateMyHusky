// Runnable self-check for the shared scroll lock (no unit-test framework is installed).
// Run: cd frontend && npx tsx src/utils/useScrollLock.selftest.ts
// Prints PASS/FAIL per check and exits non-zero on any failure.
const root = { style: { overflow: '' } };
(globalThis as unknown as { document: unknown }).document = { documentElement: root };

const { lockScroll, unlockScroll } = await import('./useScrollLock');

let failures = 0;
function check(name: string, ok: boolean) {
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}`);
  if (!ok) failures++;
}

lockScroll();
check('one lock hides overflow', root.style.overflow === 'hidden');
unlockScroll();
check('releasing it restores overflow', root.style.overflow === '');

// Sidebar opens, sign-in modal opens over it, sidebar closes first.
lockScroll();
lockScroll();
unlockScroll();
check('overlapping lock still holds after the first one closes', root.style.overflow === 'hidden');
unlockScroll();
check('page scrolls again once both close', root.style.overflow === '');

root.style.overflow = 'scroll';
lockScroll();
unlockScroll();
check('restores a non-empty previous value', root.style.overflow === 'scroll');

process.exit(failures ? 1 : 0);
