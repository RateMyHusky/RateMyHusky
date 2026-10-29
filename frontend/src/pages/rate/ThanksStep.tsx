import { useState } from 'react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { formatCode, lastName, replacedLine } from './rateFlow';
import { REFRESH_DAY } from '../../config';
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
  // A professor or course new to the site is reviewed before it shows (Faq.tsx, "Can I write
  // a review here?"). A hold for other reasons isn't told to the client, so it isn't named here.
  const needsReview = (professor && !professor.slug) || course?.isNew;
  const where = professor?.slug ? `Prof. ${lastName(professor.name)}'s page` : 'the site';
  const whenShown = needsReview
    ? `New professors and courses get a quick check first, then your rating shows on ${where} after the next ${REFRESH_DAY} update.`
    : `Your rating shows on ${where} after ${REFRESH_DAY}'s update.`;

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
      <p className="rate-hint rate-when">
        {whenShown}
        {answers.comment.trim() ? " Comments aren't shown on the site yet." : ''}
      </p>
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
