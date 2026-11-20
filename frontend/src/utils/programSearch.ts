export interface Program { name: string; college: string }

// Mirrors student_profile.MAX_PROGRAMS on the backend.
export const MAX_PROGRAMS = 4;
export const OTHER = 'other';

const words = (s: string) => s.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
const byText = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

export function searchPrograms(
  list: Program[], query: string, exclude: string[], limit = 30,
): { college: string; programs: Program[] }[] {
  const tokens = words(query);
  if (!tokens.length) return [];
  // Rank before the limit: fewest name words (before the comma) that the query doesn't touch first,
  // so "Computer Science, BSCS" beats "Computer Science and Design, BS" whatever its college.
  const extra = (p: Program) => words(p.name.split(',')[0]).filter((w) => !tokens.some((t) => w.startsWith(t))).length;
  const hits = list
    .filter((p) => !exclude.includes(p.name))
    .filter((p) => {
      const w = words(p.name);
      return tokens.every((t) => w.some((x) => x.startsWith(t)));
    })
    .map((p) => ({ p, rank: extra(p) }))
    .sort((a, b) => a.rank - b.rank || byText(a.p.name, b.p.name))
    .slice(0, limit);
  // Group by college, groups ordered by their best hit (hits are already ranked).
  const groups: { college: string; programs: Program[] }[] = [];
  for (const { p } of hits) {
    const g = groups.find((x) => x.college === p.college);
    if (g) g.programs.push(p);
    else groups.push({ college: p.college, programs: [p] });
  }
  return groups;
}
