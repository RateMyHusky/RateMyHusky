import { useState } from 'react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { formatCode, lastName, replacedLine } from './rateFlow';
import type { Answers } from './rateFlow';

interface ThanksStepProps {
  answers: Answers;
  counter: number | null;
  onRateAnother: () => void;
  popperSlot?: ReactNode;
}

export function ThanksStep({ answers, counter, onRateAnother, popperSlot }: ThanksStepProps) {
  const [copied, setCopied] = useState(false);
  const { professor, course } = answers;

  const share = async () => {
    const url = `${window.location.origin}/rate`;
    if (navigator.share) {
      try {
        await navigator.share({ url });
      } catch {
        /* the student closed the share sheet */
      }
      return;
    }
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      /* no clipboard access */
    }
  };

  return (
    <div className="rate-thanks">
      {popperSlot}
      <h1 className="rate-q" tabIndex={-1}>
        {answers.updating
          ? `Rating updated. Thanks for keeping ${course ? formatCode(course.code) : 'this course'} accurate.`
          : `Thanks! That helps every student picking ${course ? formatCode(course.code) : 'this course'}.`}
      </h1>
      {answers.updating
        ? <p className="rate-hint">{replacedLine(answers.updating)}</p>
        : counter !== null && <p className="rate-hint">You're one of {counter} Huskies who rated this term.</p>}
      <button type="button" className="rate-btn" onClick={onRateAnother}>Rate another professor</button>
      <button type="button" className="rate-ghost" onClick={share}>Share with a friend</button>
      <p className="rate-hint" role="status">{copied ? 'Link copied' : ''}</p>
      {professor?.slug && (
        <Link className="rate-ghost rate-link" to={`/professors/${professor.slug}`}>
          See Prof. {lastName(professor.name)}'s page
        </Link>
      )}
    </div>
  );
}
