import { safeHttpUrl, type TeachingAward } from '../api';
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

export default function AwardChips({
  awards,
  moreHref,
}: {
  awards: TeachingAward[];
  /** Where "+N more" goes — the professor's page lists every award in full. */
  moreHref: string;
}) {
  if (awards.length === 0) return null;

  const groups = group(awards);
  const shown = groups.slice(0, MAX_VISIBLE);
  const hidden = groups.length - shown.length;

  return (
    <ul className="awards">
      {shown.map(({ label, award, years }) => {
        // sourceUrl is scraped. Anything but absolute http(s) renders as a
        // plain chip rather than a link.
        const href = safeHttpUrl(award.sourceUrl);
        const title = `${award.award} — ${award.awardingBody} (${years.join(', ')})`;
        const body = (
          <>
            {label}
            <span className="award-years">{years.join(', ')}</span>
          </>
        );
        return (
          <li key={award.award}>
            {href ? (
              <a className="award" href={href} target="_blank" rel="noopener noreferrer" title={title}>
                {body}
              </a>
            ) : (
              <span className="award" title={title}>
                {body}
              </span>
            )}
          </li>
        );
      })}
      {hidden > 0 && (
        <li>
          {/* A link rather than a span with a title: a tooltip is unreachable
              by keyboard and unread by screen readers, and it stranded the
              hidden awards' sourceUrls. The professor's page has them all. */}
          <a className="award more" href={moreHref} target="_blank" rel="noopener noreferrer">
            +{hidden} more
          </a>
        </li>
      )}
    </ul>
  );
}
