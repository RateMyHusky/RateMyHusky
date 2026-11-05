import { useEffect, useLayoutEffect, useRef } from 'react';

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), iframe, [tabindex]:not([tabindex="-1"])';

function focusableIn(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE))
    .filter(el => el.getClientRects().length > 0);
}

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
    (initialFocusLatest.current?.current ?? focusableIn(container)[0])?.focus();

    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const onKeyDown = (e: KeyboardEvent) => {
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
      document.body.style.overflow = prevOverflow;
      if (opener instanceof HTMLElement && document.contains(opener)) opener.focus();
    };
  }, [open, containerRef]);
}
