import type { TeachingAward } from '../api';
import './AwardChips.css';

// At most this many chips; the rest collapse into "+N more". Award names run
// long ("Bouvé Graduate Distinguished Educator Award") and the popup is 380px.
const MAX_VISIBLE = 2;

/** Same grouping as the site's groupAwards: one chip per award name, with the
 *  years it was won listed after it. */
function group(awards: TeachingAward[]) {
  const groups: { label: string; award: TeachingAward; years: string[] }[] = [];
  for (const a of awards) {
    const g = groups.find((x) => x.award.award === a.award);
    if (g) g.years.push(a.yearLabel);
    else groups.push({ label: a.award.replace(/ Award$/, ''), award: a, years: [a.yearLabel] });
  }
  return groups;
}

export default function AwardChips({ awards }: { awards: TeachingAward[] }) {
  if (awards.length === 0) return null;

  const groups = group(awards);
  const shown = groups.slice(0, MAX_VISIBLE);
  const hidden = groups.length - shown.length;

  return (
    <ul className="awards">
      {shown.map(({ label, award, years }) => (
        <li key={award.award}>
          <a
            className="award"
            href={award.sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            title={`${award.award} — ${award.awardingBody} (${years.join(', ')})`}
          >
            {label}
            <span className="award-years">{years.join(', ')}</span>
          </a>
        </li>
      ))}
      {hidden > 0 && (
        <li>
          <span className="award more" title={groups.slice(MAX_VISIBLE).map((g) => g.label).join('\n')}>
            +{hidden} more
          </span>
        </li>
      )}
    </ul>
  );
}
