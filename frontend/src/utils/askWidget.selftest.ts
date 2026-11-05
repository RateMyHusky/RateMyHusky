// Runnable self-check for askWidget helpers (no unit-test framework is installed).
// Run: cd frontend && npx tsx src/utils/askWidget.selftest.ts
import { argv } from 'node:process';
import { fileURLToPath } from 'node:url';
import { withName, loadTranscript, saveTranscript, TRANSCRIPT_MAX } from './askWidget';
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

  console.log(fails.length ? `${fails.length} FAIL(s): ` + fails.join(', ') : 'ALL PASS');
  return fails.length ? 1 : 0;
}

if (argv[1] && fileURLToPath(import.meta.url) === argv[1]) {
  process.exit(selftest());
}
