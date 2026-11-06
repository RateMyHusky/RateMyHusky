import { useEffect, useLayoutEffect, useRef } from 'react';
import { lockScroll, unlockScroll } from './useScrollLock';

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), iframe, [tabindex]:not([tabindex="-1"])';

function focusableIn(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE))
    .filter(el => el.getClientRects().length > 0);
}

// Open dialogs, oldest first. Only the last one handles keys, so a dialog opened over the filter drawer
// takes Esc and Tab alone. Each one holds the shared scroll lock, so the page scrolls again only once all have closed.
const openDialogs: object[] = [];

/** Whether any dialog is open, for page-level Esc handlers that must leave Esc to it. */
export const dialogOpen = (): boolean => openDialogs.length > 0;

/**
 * Focus, Tab trap, Esc and scroll lock for a modal dialog. Focus moves in when it opens
 * (initialFocusRef, else the first focusable) and returns to the opener when it closes.
 * Esc is skipped when a control inside already handled it (e.g. an open Dropdown list).
 */
export function useDialog(
  open: boolean,
  onClose: () => void,
  containerRef: React.RefObject<HTMLElement | null>,
  initialFocusRef?: React.RefObject<HTMLElement | null>,
): void {
  // Latest values live in refs so a new onClose, or an initial-focus target that changes
  // while the dialog is open, never re-runs the main effect and yanks focus.
  const onCloseRef = useRef(onClose);
  const initialFocusLatest = useRef(initialFocusRef);
  useLayoutEffect(() => {
    onCloseRef.current = onClose;
    initialFocusLatest.current = initialFocusRef;
  });

  useEffect(() => {
    if (!open) return;
    const container = containerRef.current;
    if (!container) return;

    const opener = document.activeElement;
    // preventScroll: a drawer still sliding in from offscreen would otherwise scroll the page to the top.
    (initialFocusLatest.current?.current ?? focusableIn(container)[0])?.focus({ preventScroll: true });

    const token = {};
    openDialogs.push(token);
    lockScroll();

    const onKeyDown = (e: KeyboardEvent) => {
      if (openDialogs[openDialogs.length - 1] !== token) return;
      if (e.key === 'Escape') {
        if (!e.defaultPrevented) {
          e.preventDefault();
          onCloseRef.current();
        }
        return;
      }
      if (e.key !== 'Tab') return;
      const items = focusableIn(container);
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (!active || !container.contains(active)) {
        e.preventDefault();
        first.focus();
      } else if (e.shiftKey && active === first) {
        e.preventDefault();
        items.filter(el => !el.hasAttribute('data-dialog-wrap')).pop()?.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    };
    // A [data-dialog-wrap] element at the end of a dialog catches native Tab leaving a widget
    // the hook can't see into (Turnstile's iframe is in a closed shadow root) and wraps to the first item.
    const onFocusIn = (e: FocusEvent) => {
      if ((e.target as HTMLElement).hasAttribute('data-dialog-wrap')) focusableIn(container)[0]?.focus();
    };
    document.addEventListener('keydown', onKeyDown);
    container.addEventListener('focusin', onFocusIn);

    return () => {
      document.removeEventListener('keydown', onKeyDown);
      container.removeEventListener('focusin', onFocusIn);
      openDialogs.splice(openDialogs.indexOf(token), 1);
      unlockScroll();
      if (opener instanceof HTMLElement && document.contains(opener)) opener.focus();
    };
  }, [open, containerRef]);
}
