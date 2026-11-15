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

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const isStr = (v: unknown): v is string => typeof v === 'string';
const listOf = (v: unknown, item: (x: Record<string, unknown>) => boolean) =>
  Array.isArray(v) && v.every((x) => isObj(x) && item(x));

/** True when AskAnswer can render `r` without throwing: the fields each mode dereferences
    are present with the right types. Modes AskAnswer reads only through `??` fallbacks
    (keyword, out_of_scope, thin_data, and any unknown mode) need just a string mode. */
export function isRenderableResult(r: unknown): r is ChatResponse {
  if (!isObj(r) || !isStr(r.mode)) return false;
  switch (r.mode) {
    case 'question':
      return isStr(r.answer)
        && (r.sources === undefined || listOf(r.sources, (s) => typeof s.source_id === 'number'))
        && (r.cited === undefined || Array.isArray(r.cited))
        && (r.course_code == null || isStr(r.course_code));
    case 'disambiguation':
      return isStr(r.message) && listOf(r.matches, (m) => isStr(m.name));
    case 'course_list':
      return isStr(r.answer)
        && listOf(r.courses, (c) => isStr(c.code) && (c.rating == null || typeof c.rating === 'number'));
    case 'site_help':
      return isStr(r.answer) && listOf(r.links, (l) => isStr(l.href) && isStr(l.label))
        && (r.menu === undefined || listOf(r.menu, (m) => isStr(m.id) && isStr(m.title)));
    case 'site_help_choice':
      return isStr(r.message) && listOf(r.options, (o) => isStr(o.id) && isStr(o.title));
    case 'error':
      return isStr(r.message);
    default:
      return true;
  }
}

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
        (!('result' in m) || isRenderableResult(m.result)),
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

/** A /api/chat JSON body the widget can't render (the {"error": ...} bodies of a 429 or a
    500, or a mode missing its fields) becomes an error reply, so the widget never shows an
    empty bubble or crashes. */
export function chatBodyOrError(body: unknown): ChatResponse {
  if (isRenderableResult(body)) return body;
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
