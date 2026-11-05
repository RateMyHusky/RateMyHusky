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
      (m) => m && typeof m === 'object' && typeof m.id === 'number' && (m.from === 'bot' || m.from === 'user'),
    );
    return valid ? (parsed as WidgetMsg[]) : null;
  } catch {
    return null;
  }
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

/** Replaces the ambiguous name in the question with the picked full name (whole-word,
    case-insensitive); falls back to prefixing the pick when the name is not found. */
export function withName(question: string, ambiguous: string | undefined, pick: string): string {
  if (ambiguous) {
    const escaped = ambiguous.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const re = new RegExp(`(?<![\\w])${escaped}(?![\\w])`, 'i');
    if (re.test(question)) return question.replace(re, () => pick);
  }
  return `${pick}: ${question}`;
}
