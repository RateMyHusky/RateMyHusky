// Runnable self-check for askPinMatch (no unit-test framework is installed).
// Run: cd frontend && npx tsx src/utils/askPinMatch.selftest.ts
// Prints PASS/FAIL per check and exits non-zero on any failure.
import { argv } from 'node:process';
import { fileURLToPath } from 'node:url';
import { matchesPin, isPinned, pinnedFirst, pinClickKey } from './askPinMatch';

function selftest(): number {
  const fails: string[] = [];
  const check = (label: string, cond: boolean) => {
    if (!cond) fails.push(label);
    console.log((cond ? 'PASS' : 'FAIL') + ': ' + label);
  };

  const longBody = 'Took CS3500 with him. Hard but fair, great office hours, learned a ton about systems design and testing methodology over the whole semester.';
  const snippet200 = longBody.slice(0, 130); // stand-in for a 200-char prefix shorter than body

  check('exact match', matchesPin('hard but fair', 'hard but fair'));
  check('prefix match (snippet is prefix of longer body)', matchesPin(longBody, snippet200));
  check('whitespace-difference match', matchesPin('hard   but\n fair', 'hard but fair'));
  check('body shorter than snippet still matches when body covers >=80% of snippet', matchesPin('hard but fai', 'hard but fair'));
  check('non-match', !matchesPin('totally unrelated comment', 'hard but fair'));
  check('empty snippet never matches', !matchesPin('hard but fair', ''));
  check('empty body never matches', !matchesPin('', 'hard but fair'));

  // Issue 11: bidirectional-prefix false match — a short review whose full text is a tiny
  // prefix of an unrelated longer snippet must NOT match; the true full review still matches;
  // small length drift (195 vs 200 chars) still matches.
  const realSnippet = 'Great professor. However the exams were brutal and the curve barely helped. Office hours were useful but hard to get into since everyone showed up right before the midterm and final.';
  check('short review that is a tiny prefix of an unrelated snippet does not match (Issue 11)',
    !matchesPin('Great professor.', realSnippet));
  check('true full review (long, >=80% of snippet) matches (Issue 11)',
    matchesPin(realSnippet, realSnippet));
  const snippet200Chars = (realSnippet + ' Would take again for sure honestly.').slice(0, 200);
  const body195 = snippet200Chars.slice(0, 195);
  check('body 195 chars vs 200-char snippet still matches (Issue 11)', matchesPin(body195, snippet200Chars));

  // Issue 29: decodeEntities must run unconditionally, not only when '&' is present, so a body
  // with tag-like text and an '&' appearing only after char 200 still normalizes the same as the
  // snippet (which is body[:200] and may not contain the '&' at all).
  const bodyWithTagAndLateAmp = '<insane> ' + 'x'.repeat(200) + ' foo & bar';
  const snippetNoAmp = bodyWithTagAndLateAmp.slice(0, 200);
  check('snippet without "&" still matches body containing tag + late "&" (Issue 29)',
    matchesPin(bodyWithTagAndLateAmp, snippetNoAmp));

  const items = [{ b: 'zeta review' }, { b: longBody }, { b: 'alpha review' }];
  const out = pinnedFirst(items, (x) => x.b, [snippet200]);
  check('pinnedFirst hoists match to front', out[0].b === longBody);
  check('pinnedFirst preserves rest order', out[1].b === 'zeta review' && out[2].b === 'alpha review');
  check('pinnedFirst no-op on empty snippets', pinnedFirst(items, (x) => x.b, []) === items);

  check('isPinned true on any match', isPinned(longBody, ['nope', snippet200]));
  check('isPinned false when none match', !isPinned('nope', ['other', 'thing']));

  // Regression: evidence-table snippet keeps HTML entities; page body is html.unescape'd.
  check('html-entity snippet matches unescaped body (&amp; / apostrophe)',
    matchesPin("Rowe & the TA were great, don't skip", 'Rowe &amp; the TA were great, don&#39;t skip'));
  // Regression: NFKC ligature/superscript normalizes on both sides.
  check('NFKC ligature/superscript match', matchesPin('final exam x2 was difficult', 'ﬁnal exam x² was diﬃcult') || matchesPin('ﬁnal exam x² was diﬃcult', 'final exam x2 was difficult'));

  // The professor page re-applies pins (tab switch + scroll) once per distinct citation click,
  // so [2] then [3] from the same answer both act.
  const a = { askedAt: 1700000000000, clicked: { source: 'rmp', snippet: 'hard but fair' } };
  check('pinClickKey: same click, same key', pinClickKey(a) === pinClickKey({ ...a, clicked: { ...a.clicked } }));
  check('pinClickKey: another citation in the same answer differs',
    pinClickKey(a) !== pinClickKey({ ...a, clicked: { source: 'reddit', snippet: 'hard but fair' } })
    && pinClickKey(a) !== pinClickKey({ ...a, clicked: { source: 'rmp', snippet: 'easy grader' } }));
  check('pinClickKey: a new answer differs', pinClickKey(a) !== pinClickKey({ ...a, askedAt: a.askedAt + 1 }));
  check('pinClickKey: no delimiter collision',
    pinClickKey({ askedAt: 1, clicked: { source: 'a|b', snippet: 'c' } }) !== pinClickKey({ askedAt: 1, clicked: { source: 'a', snippet: 'b|c' } }));
  check('pinClickKey: never the empty "nothing applied" sentinel', pinClickKey({ askedAt: 0, clicked: { source: null, snippet: '' } }) !== '');

  console.log(fails.length ? `${fails.length} FAIL(s): ` + fails.join(', ') : 'ALL PASS');
  return fails.length ? 1 : 0;
}

if (argv[1] && fileURLToPath(import.meta.url) === argv[1]) {
  process.exit(selftest());
}
