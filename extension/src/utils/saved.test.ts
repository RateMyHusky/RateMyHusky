import { describe, expect, it } from 'vitest';
import { isSaved, normalize, SLUG } from './saved';

describe('SLUG', () => {
  it('accepts site slugs and rejects anything that could break out of a URL', () => {
    expect(SLUG.test('peggy-o-kelly')).toBe(true);
    expect(SLUG.test('../admin')).toBe(false);
    expect(SLUG.test('a b')).toBe(false);
    expect(SLUG.test('-leading')).toBe(false);
    expect(SLUG.test('x'.repeat(121))).toBe(false);
  });
});

describe('normalize', () => {
  it('keeps only the professor, dropping any Banner details an old entry had', () => {
    const legacy = {
      slug: 'john-rachlin',
      name: 'Rachlin, John',
      course: 'CS 3200 · Database Design',
      term: '202730',
      crn: '30351',
      savedAt: 1,
    };
    expect(normalize([legacy])).toEqual([{ slug: 'john-rachlin', name: 'Rachlin, John', savedAt: 1 }]);
  });

  it('keeps one entry per professor, the first one seen', () => {
    const out = normalize([
      { slug: 'a', name: 'A', savedAt: 2 },
      { slug: 'a', name: 'A', savedAt: 1 },
      { slug: 'b', name: 'B', savedAt: 3 },
    ]);
    expect(out.map((s) => [s.slug, s.savedAt])).toEqual([['a', 2], ['b', 3]]);
  });

  it('drops malformed entries', () => {
    expect(normalize([null, 'x', { slug: 'BAD', name: 'X', savedAt: 1 }, { slug: 'ok', name: '', savedAt: 1 }])).toEqual([]);
  });

  it('caps the list', () => {
    const many = Array.from({ length: 150 }, (_, i) => ({ slug: `p${i}`, name: 'P', savedAt: i }));
    expect(normalize(many)).toHaveLength(100);
  });
});

describe('isSaved', () => {
  it('requires a finite timestamp', () => {
    expect(isSaved({ slug: 'a', name: 'A', savedAt: Number.NaN })).toBe(false);
  });
});
