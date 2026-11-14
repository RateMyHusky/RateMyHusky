// Runnable self-check for askWidget helpers (no unit-test framework is installed).
// Run: cd frontend && npx tsx src/utils/askWidget.selftest.ts
import { argv } from 'node:process';
import { fileURLToPath } from 'node:url';
import { withName, loadTranscript, saveTranscript, clearTranscript, chatBodyOrError, TRANSCRIPT_KEY, TRANSCRIPT_MAX } from './askWidget';
import type { WidgetMsg } from './askWidget';

function fakeStorage(init: Record<string, string>): Storage {
  const m = new Map(Object.entries(init));
  return {
    get length() { return m.size; },
    clear: () => m.clear(),
    getItem: (k: string) => (m.has(k) ? m.get(k)! : null),
    key: (i: number) => Array.from(m.keys())[i] ?? null,
    removeItem: (k: string) => { m.delete(k); },
    setItem: (k: string, v: string) => { m.set(k, String(v)); },
  };
}

function throwingStorage(): Storage {
  const boom = () => { throw new Error('storage unavailable'); };
  return { length: 0, clear: boom, getItem: boom, key: boom, removeItem: boom, setItem: boom };
}

function msgs(n: number): WidgetMsg[] {
  return Array.from({ length: n }, (_, i) => ({ id: i, from: i % 2 ? 'bot' : 'user', text: `m${i}` }) as WidgetMsg);
}

function selftest(): number {
  const fails: string[] = [];
  const check = (label: string, cond: boolean) => {
    if (!cond) fails.push(label);
    console.log((cond ? 'PASS' : 'FAIL') + ': ' + label);
  };

  check('withName swaps a surname', withName('is lee hard?', 'Lee', 'Wei Lee') === 'is Wei Lee hard?');
  check('withName escapes metacharacters', withName("is O'Brien.? fair", "O'Brien.?", "Ann O'Brien") === "is Ann O'Brien fair");
  check('withName handles a dotted name', withName('is st. john hard', 'St. John', 'Mary St. John') === 'is Mary St. John hard');
  check('withName falls back when absent', withName('is he hard', 'Lee', 'Wei Lee') === 'Wei Lee: is he hard');
  check('withName falls back without ambiguous', withName('x', undefined, 'CS2500') === 'CS2500: x');
  check('withName does not match inside a longer word', withName('is leeway ok', 'Lee', 'Wei Lee') === 'Wei Lee: is leeway ok');
  check('withName treats $ in pick literally', withName('is lee hard', 'Lee', "A$&B") === 'is A$&B hard');

  check('load: missing key -> null', loadTranscript(fakeStorage({})) === null);
  check('load: bad JSON -> null', loadTranscript(fakeStorage({ ask_widget_v1: '{oops' })) === null);
  check('load: old shape -> null', loadTranscript(fakeStorage({ ask_widget_v1: '{"query":"x"}' })) === null);
  check('load: bad element -> null', loadTranscript(fakeStorage({ ask_widget_v1: '[{"id":1,"from":"bot"},{"id":"2","from":"user"}]' })) === null);
  check('load: bad from -> null', loadTranscript(fakeStorage({ ask_widget_v1: '[{"id":1,"from":"system"}]' })) === null);
  check('load: throwing storage -> null', loadTranscript(throwingStorage()) === null);
  check('save/load round trip', (() => { const s = fakeStorage({}); saveTranscript(msgs(3), s); const r = loadTranscript(s); return !!r && r.length === 3 && r[2].text === 'm2'; })());
  check('save keeps last 30', (() => { const s = fakeStorage({}); saveTranscript(msgs(40), s); const r = loadTranscript(s)!; return r.length === TRANSCRIPT_MAX && r[0].id === 10; })());
  check('save on throwing storage does not throw', (() => { saveTranscript(msgs(1), throwingStorage()); return true; })());
  check('default storage absent (node) does not throw', (() => { saveTranscript(msgs(1)); return loadTranscript() === null; })());

  // A saved result the widget can't render must not be replayed into it after a reload.
  check('load: result with a mode -> kept', (() => { const r = loadTranscript(fakeStorage({ ask_widget_v1: '[{"id":1,"from":"bot","result":{"mode":"error","message":"x"}}]' })); return !!r && r.length === 1; })());
  check('load: result without a mode -> null', loadTranscript(fakeStorage({ ask_widget_v1: '[{"id":1,"from":"bot","result":{"error":"x"}}]' })) === null);
  check('load: result with a non-string mode -> null', loadTranscript(fakeStorage({ ask_widget_v1: '[{"id":1,"from":"bot","result":{"mode":3}}]' })) === null);
  check('load: result that is not an object -> null', loadTranscript(fakeStorage({ ask_widget_v1: '[{"id":1,"from":"bot","result":"answer"}]' })) === null);
  check('load: null result -> null', loadTranscript(fakeStorage({ ask_widget_v1: '[{"id":1,"from":"bot","result":null}]' })) === null);

  check('clearTranscript removes the saved transcript', (() => { const s = fakeStorage({}); saveTranscript(msgs(2), s); clearTranscript(s); return s.getItem(TRANSCRIPT_KEY) === null; })());
  check('clearTranscript on throwing storage does not throw', (() => { clearTranscript(throwingStorage()); return true; })());
  check('clearTranscript with no default storage (node) does not throw', (() => { clearTranscript(); return true; })());

  // 429 and 500 bodies are {"error": ...}: they must become an error bubble, never an empty one.
  const fallback = 'Something went wrong — try again.';
  const asErr = (b: unknown, msg: string) => { const r = chatBodyOrError(b); return r.mode === 'error' && r.message === msg; };
  check('chatBody: {error} -> error with its message', asErr({ error: 'Internal server error' }, 'Internal server error'));
  check('chatBody: {} -> error with the fallback', asErr({}, fallback));
  check('chatBody: non-string error -> fallback', asErr({ error: 42 }, fallback));
  check('chatBody: null -> fallback', asErr(null, fallback));
  check('chatBody: array -> fallback', asErr([], fallback));
  check('chatBody: non-string mode -> fallback', asErr({ mode: 7 }, fallback));
  check('chatBody: a body with a mode passes through', (() => { const b = { mode: 'error', message: 'Sign in to use Ask mode.' }; return chatBodyOrError(b) === b; })());

  // Old Safari has no lookbehind: building the RegExp throws there, and the pick is prefixed.
  check('withName falls back when RegExp construction throws', (() => {
    const RealRegExp = globalThis.RegExp;
    globalThis.RegExp = function () { throw new SyntaxError('Invalid regular expression: invalid group specifier name'); } as unknown as RegExpConstructor;
    try {
      return withName('is lee hard?', 'Lee', 'Wei Lee') === 'Wei Lee: is lee hard?';
    } finally {
      globalThis.RegExp = RealRegExp;
    }
  })());

  console.log(fails.length ? `${fails.length} FAIL(s): ` + fails.join(', ') : 'ALL PASS');
  return fails.length ? 1 : 0;
}

if (argv[1] && fileURLToPath(import.meta.url) === argv[1]) {
  process.exit(selftest());
}
