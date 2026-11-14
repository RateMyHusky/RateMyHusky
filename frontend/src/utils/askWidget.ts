// Pure helpers for the Ask widget: transcript persistence and disambiguation rewrites.
import type { ChatResponse } from '../api/api';

export type WidgetMsg = {
  id: number;
  from: 'bot' | 'user';
  text?: string;
  result?: ChatResponse;
  status?: number;
  askedAt?: number;
  question?: string;
};

export const TRANSCRIPT_KEY = 'ask_widget_v1';
export const TRANSCRIPT_MAX = 30;

/** Returns null on missing/corrupt data or an unavailable storage. */
export function loadTranscript(storage?: Storage): WidgetMsg[] | null {
  try {
    const store = storage ?? window.sessionStorage;
    const raw = store.getItem(TRANSCRIPT_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return null;
    const valid = parsed.every(
      (m) =>
        m && typeof m === 'object' && typeof m.id === 'number' && (m.from === 'bot' || m.from === 'user') &&
        // A result the widget can't render would crash it again on every reload.
        (!('result' in m) || (!!m.result && typeof m.result === 'object' && typeof m.result.mode === 'string')),
    );
    return valid ? (parsed as WidgetMsg[]) : null;
  } catch {
    return null;
  }
}

/** Fired on window by clearTranscript, so a mounted widget drops the conversation it shows. */
export const TRANSCRIPT_CLEARED_EVENT = 'ask-transcript-cleared';

/** Forgets the saved transcript (on sign-out) and tells the widget to reset; storage
    failures are ignored. */
export function clearTranscript(storage?: Storage): void {
  try {
    const store = storage ?? window.sessionStorage;
    store.removeItem(TRANSCRIPT_KEY);
  } catch {
    /* ignore */
  }
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(TRANSCRIPT_CLEARED_EVENT));
}

/** Persists the last TRANSCRIPT_MAX messages; storage failures are ignored. */
export function saveTranscript(msgs: WidgetMsg[], storage?: Storage): void {
  try {
    const store = storage ?? window.sessionStorage;
    store.setItem(TRANSCRIPT_KEY, JSON.stringify(msgs.slice(-TRANSCRIPT_MAX)));
  } catch {
    /* ignore */
  }
}

/** A /api/chat JSON body without a string `mode` (the {"error": ...} bodies of a 429 or a
    500) becomes an error reply, so the widget never shows an empty bubble. */
export function chatBodyOrError(body: unknown): ChatResponse {
  if (body && typeof body === 'object' && !Array.isArray(body) && typeof (body as { mode?: unknown }).mode === 'string') {
    return body as ChatResponse;
  }
  const error = body && typeof body === 'object' ? (body as { error?: unknown }).error : undefined;
  return { mode: 'error', message: typeof error === 'string' && error ? error : 'Something went wrong — try again.' };
}

/** Replaces the ambiguous name in the question with the picked full name (whole-word,
    case-insensitive); falls back to prefixing the pick when the name is not found. */
export function withName(question: string, ambiguous: string | undefined, pick: string): string {
  if (ambiguous) {
    const escaped = ambiguous.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    let re: RegExp | null = null;
    try {
      re = new RegExp(`(?<![\\w])${escaped}(?![\\w])`, 'i');
    } catch {
      // Old Safari has no lookbehind and throws here; the prefix form still works.
    }
    if (re && re.test(question)) return question.replace(re, () => pick);
  }
  return `${pick}: ${question}`;
}
