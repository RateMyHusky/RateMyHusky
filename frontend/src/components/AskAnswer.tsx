import { Link } from 'react-router-dom';
import type { ChatResponse } from '../api/api';
import './AskAnswer.css';

// What a chip in an answer asks the host to do next: open a help topic, re-ask with a name,
// or ("No, other" on the site-help prompt) send the question on to the LLM.
export type AskPick = { kind: 'help'; id: string } | { kind: 'name'; pick: string } | { kind: 'other' };

// Route state for links out of an answer. fromAsk lets the homepage scroll to /#goated;
// professor citations spread askPins onto it for the Professor page's highlighting.
const ASK_LINK_STATE = { fromAsk: true };

const SOURCE_LABEL: Record<string, string> = {
  reddit: "Reddit",
  rmp: "RateMyProfessor",
};

export default function AskAnswer({ result, askedAt, onPick }: { result: ChatResponse; askedAt: number; onPick?: (p: AskPick) => void }) {
  if (result.mode === 'question') {
    // Fallback entity (used when a source has no per-source tag, e.g. old cached answers).
    const fallbackHref = result.course_code
      ? `/courses/${result.course_code.toLowerCase()}`
      : result.professor_slug
      ? `/professors/${result.professor_slug}`
      : null;
    // Show a source only if it's actually cited. Prefer the backend's validated `cited` list
    // (handles grouped citations like [1, 2]); fall back to the substring probe for older
    // cached payloads that predate the field.
    const sources = result.sources ?? [];
    const cited = Array.isArray(result.cited)
      ? sources.filter((s) => result.cited!.includes(s.source_id))
      : sources.filter((s) => result.answer.includes(`[${s.source_id}]`));
    return (
      <>
        <p className="ask-answer">{result.answer}</p>
        {cited.length > 0 && (
          <ol className="ask-sources">
            {cited.map((s) => {
              // Course citations win the course link (courses page has no pin behavior yet).
              const courseHref = s.course_code ? `/courses/${s.course_code.toLowerCase()}` : null;
              const profHref = s.professor_slug ? `/professors/${s.professor_slug}` : null;
              const href = courseHref ?? profHref ?? fallbackHref;
              // Pins only travel to professor pages, and only for citations whose destination
              // is a professor (no course_code). Carry every cited source sharing this slug.
              const pinToProfessor = !s.course_code && !!s.professor_slug;
              const sourcesForEntity = pinToProfessor
                ? cited
                    .filter((o) => !o.course_code && o.professor_slug === s.professor_slug)
                    .map((o) => ({ source: o.source ?? null, snippet: o.snippet }))
                : [];
              const linkProps = pinToProfessor
                ? {
                    state: {
                      ...ASK_LINK_STATE,
                      askPins: {
                        askedAt,
                        clicked: { source: s.source ?? null, snippet: s.snippet },
                        sources: sourcesForEntity,
                      },
                    },
                  }
                : { state: ASK_LINK_STATE };
              return (
                <li key={s.source_id}>
                  {href ? (
                    <Link className="ask-source-link" to={href} {...linkProps}>[{s.source_id}]</Link>
                  ) : (
                    <span className="ask-source-link">[{s.source_id}]</span>
                  )}
                  <span className="ask-source-badge">{SOURCE_LABEL[s.source ?? ''] ?? 'Reddit'}</span>
                  <span className="ask-source-snippet">{s.snippet}</span>
                </li>
              );
            })}
          </ol>
        )}
        <p className="ask-disclaimer">{result.disclaimer}</p>
      </>
    );
  }

  if (result.mode === 'disambiguation') {
    return (
      <>
        <p className="ask-answer">{result.message}</p>
        {result.matches.length > 0 && (
          <div className="ask-chips">
            {result.matches.map((m) => (
              <button
                key={m.pick ?? m.name}
                type="button"
                className="ask-chip"
                onClick={() => onPick?.({ kind: 'name', pick: m.pick ?? m.name })}
              >
                {m.name}
              </button>
            ))}
          </div>
        )}
      </>
    );
  }

  if (result.mode === 'error') {
    return <p className="ask-answer">{result.message}</p>;
  }

  if (result.mode === 'course_list') {
    return (
      <>
        <p className="ask-answer">{result.answer}</p>
        {result.courses.length > 0 && (
          <ol className="ask-sources">
            {result.courses.map((c) => (
              <li key={c.code}>
                <Link className="ask-source-link" to={`/courses/${c.code.toLowerCase()}`} state={ASK_LINK_STATE}>{c.code}</Link>
                <span className="ask-source-snippet">
                  {c.name}{c.rating != null ? ` · ${c.rating.toFixed(1)}★` : ''}
                </span>
              </li>
            ))}
          </ol>
        )}
        <p className="ask-disclaimer">{result.disclaimer}</p>
      </>
    );
  }

  if (result.mode === 'site_help_choice') {
    return (
      <>
        <p className="ask-answer">{result.message}</p>
        <div className="ask-chips">
          {result.options.map((o) => (
            <button
              key={o.id}
              type="button"
              className="ask-chip"
              onClick={() => onPick?.({ kind: 'help', id: o.id })}
            >
              {o.title}
            </button>
          ))}
          <button type="button" className="ask-chip" onClick={() => onPick?.({ kind: 'other' })}>
            No, other
          </button>
        </div>
      </>
    );
  }

  if (result.mode === 'site_help') {
    return (
      <>
        <p className="ask-answer">{result.answer}</p>
        {result.links.length > 0 && (
          <ul className="ask-help-links">
            {result.links.map((l) => (
              <li key={l.href}>
                <Link className="ask-source-link" to={l.href} state={ASK_LINK_STATE}>{l.label}</Link>
              </li>
            ))}
          </ul>
        )}
        {result.menu && result.menu.length > 0 && (
          <div className="ask-chips">
            {result.menu.map((m) => (
              <button
                key={m.id}
                type="button"
                className="ask-chip"
                onClick={() => onPick?.({ kind: 'help', id: m.id })}
              >
                {m.title}
              </button>
            ))}
          </div>
        )}
      </>
    );
  }

  // out_of_scope | thin_data | keyword — banner/message + any keyword comments
  type KeywordComment = {
    snippet?: string;
    link?: { type: 'professor' | 'course'; value: string } | null;
  };
  const keywordComments = (result.comments ?? []).slice(0, 3) as KeywordComment[];
  return (
    <>
      {(result.banner || result.message) && (
        <p className="ask-answer">{result.banner || result.message}</p>
      )}
      {keywordComments.length > 0 && (
        <ol className="ask-sources">
          {keywordComments.map((com, i) => {
            // [N] citation links to the matched professor/course profile; plain when none.
            const href = com.link
              ? com.link.type === 'course'
                ? `/courses/${com.link.value.toLowerCase()}`
                : `/professors/${com.link.value}`
              : null;
            // Keyword comments are Reddit-sourced. For a professor link, carry every visible
            // comment pinned to the same professor so the Professor page can hoist + highlight
            // them (same shape the LLM path sends); the clicked one drives the scroll.
            const pinToProfessor = com.link?.type === 'professor';
            const sourcesForEntity = pinToProfessor
              ? keywordComments
                  .filter((o) => o.link?.type === 'professor' && o.link.value === com.link!.value)
                  .map((o) => ({ source: 'reddit' as const, snippet: o.snippet ?? '' }))
              : [];
            const linkState = pinToProfessor
              ? {
                  ...ASK_LINK_STATE,
                  askPins: {
                    askedAt,
                    clicked: { source: 'reddit' as const, snippet: com.snippet ?? '' },
                    sources: sourcesForEntity,
                  },
                }
              : ASK_LINK_STATE;
            const marker = `[${i + 1}]`;
            return (
              <li key={i}>
                {href ? (
                  <Link className="ask-source-link" to={href} state={linkState}>{marker}</Link>
                ) : (
                  <span className="ask-source-link">{marker}</span>
                )}
                <span className="ask-source-snippet">{com.snippet}</span>
              </li>
            );
          })}
        </ol>
      )}
    </>
  );
}

