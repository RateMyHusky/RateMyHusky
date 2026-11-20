export interface Program { name: string; college: string }

// Mirrors student_profile.MAX_PROGRAMS on the backend.
export const MAX_PROGRAMS = 4;
export const OTHER = 'other';

const words = (s: string) => s.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
const byText = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

export function searchPrograms(
  list: Program[], query: string, exclude: string[], limit = 30,
): { college: string; programs: Program[] }[] {
  const tokens = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!tokens.length) return [];
  const hits = list
    .filter((p) => !exclude.includes(p.name))
    .filter((p) => {
      const w = words(p.name);
      return tokens.every((t) => w.some((x) => x.startsWith(t)));
    })
    .sort((a, b) => byText(a.college, b.college) || byText(a.name, b.name))
    .slice(0, limit);
  const groups: { college: string; programs: Program[] }[] = [];
  for (const p of hits) {
    const last = groups[groups.length - 1];
    if (last && last.college === p.college) last.programs.push(p);
    else groups.push({ college: p.college, programs: [p] });
  }
  return groups;
}
