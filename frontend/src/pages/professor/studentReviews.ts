export type ReviewTab = 'students' | 'rmp' | 'reddit';

/** The first tab with something in it, in tab order; RMP when all are empty. */
export function defaultTab(counts: Record<ReviewTab, number>): ReviewTab {
  return (['students', 'rmp', 'reddit'] as const).find(t => counts[t] > 0) ?? 'rmp';
}

/** No selection is every review, including ones whose course isn't in the filter's options. */
export function filterByCourses<T extends { course: string | null }>(reviews: T[], selected: Set<string>): T[] {
  return selected.size === 0 ? reviews : reviews.filter(r => r.course !== null && selected.has(r.course));
}

export const reportDescription = (slug: string, id: string): string =>
  `Reporting RateMyHusky review ${id} on /professors/${slug}. Reason: `;
