import { lookup } from './messages';

/** Runs on Banner's Browse Classes pages. Steps 6-8 fill this in: read the CRN
 *  and Term columns off each row, ask the worker about them in one call,
 *  decorate the Title cell, and re-apply after the grid re-renders on sort,
 *  page and filter.
 *
 *  Decorating an existing cell rather than adding a column is deliberate — the
 *  results table owns its own column model and rebuilds it on every render, so
 *  an injected <th> has to be fought for forever. Appending inside a cell
 *  leaves the column count alone. */

// Proof of life, and the first thing to check when nothing happens. A content
// script built as an ES module doesn't throw — it never executes at all, and
// no console anywhere says so. If this line is missing from the page console,
// the IIFE build pass is what's broken; don't debug anything else first.
console.log('[RateMyHusky] banner content script loaded');

// Referenced so the import survives until step 6 uses it for real.
void lookup;
