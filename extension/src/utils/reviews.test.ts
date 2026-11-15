import { describe, expect, it } from 'vitest';
import type { Review, StudentReview } from '../api';
import { mergeReviews, sortReviews, termTime } from './reviews';

const rmp = (r: Partial<Review>): Review => ({
  course: '',
  courseCode: null,
  quality: 3,
  difficulty: 3,
  date: '',
  tags: '',
  comment: '',
  ...r,
});
const rmh = (r: Partial<StudentReview>): StudentReview => ({
  id: 'x',
  course: null,
  when: null,
  rating: 3,
  comment: '',
  ...r,
});

describe('termTime', () => {
  it('orders terms by year, then season', () => {
    expect(termTime('Spring 2026')).toBeLessThan(termTime('Summer 2026'));
    expect(termTime('Summer 2026')).toBeLessThan(termTime('Fall 2026'));
    expect(termTime('Fall 2025')).toBeLessThan(termTime('Spring 2026'));
  });

  it('puts anything it cannot read last', () => {
    expect(termTime(null)).toBe(0);
    expect(termTime('Sometime')).toBe(0);
  });
});

describe('mergeReviews', () => {
  it('labels each review with where it came from', () => {
    const out = mergeReviews([rmp({ comment: 'r' })], [rmh({ comment: 's' })]);
    expect(out.map((r) => [r.source, r.comment])).toEqual([['rmh', 's'], ['rmp', 'r']]);
  });

  it('splits RMP tags and lowercases them', () => {
    const [r] = mergeReviews([rmp({ tags: 'EXTRA CREDIT--Clear grading criteria--' })], []);
    expect(r.tags).toEqual(['extra credit', 'clear grading criteria']);
  });

  it('gives word-for-word duplicates distinct keys', () => {
    const same = rmp({ date: '2026-04-01', comment: 'Great' });
    const keys = mergeReviews([same, same], []).map((r) => r.key);
    expect(new Set(keys).size).toBe(2);
  });
});

describe('sortReviews', () => {
  const items = mergeReviews(
    [rmp({ quality: 2, date: '2026-04-01' }), rmp({ quality: 5, date: '2024-01-01' })],
    [rmh({ id: 'a', rating: 4, when: 'Fall 2025' })],
  );

  it('sorts newest first across both sources', () => {
    expect(sortReviews(items, 'newest').map((r) => r.rating)).toEqual([2, 4, 5]);
  });

  it('sorts by rating either way', () => {
    expect(sortReviews(items, 'highest').map((r) => r.rating)).toEqual([5, 4, 2]);
    expect(sortReviews(items, 'lowest').map((r) => r.rating)).toEqual([2, 4, 5]);
  });
});
