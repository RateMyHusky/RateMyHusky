import { describe, expect, it } from 'vitest';
import { isSearchResult, readNames, stillTeaching } from './table';

describe('stillTeaching', () => {
  it('passes when our instructor is among the names on the page', () => {
    expect(stillTeaching('Rachlin, John', ['Rachlin, John'])).toBe(true);
    expect(stillTeaching('Goldman, William', ["O'Kelly, Peggy", 'Goldman, William'])).toBe(true);
  });

  it('ignores case and stray whitespace', () => {
    expect(stillTeaching('Rachlin,  John', ['rachlin, john '])).toBe(true);
  });

  it('fails when the section was reassigned since our scrape', () => {
    expect(stillTeaching('Rachlin, John', ['Kaeli, David'])).toBe(false);
  });

  it('fails on an escaped name, which is why the endpoint unescapes', () => {
    expect(stillTeaching('O&#39;Kelly, Peggy', ["O'Kelly, Peggy"])).toBe(false);
  });

  it('passes when either side is unknown — it only ever says no', () => {
    expect(stillTeaching('Rachlin, John', null)).toBe(true);
    expect(stillTeaching(null, ['Rachlin, John'])).toBe(true);
  });
});

/** Just enough of an element for these: which selectors match. */
const row = (properties: string[]) => ({
  querySelector: (sel: string) =>
    properties.some((p) => sel.includes(`data-property="${p}"`)) ? ({} as Element) : null,
});

describe('isSearchResult', () => {
  it('takes class-search rows, which list subject and number', () => {
    expect(isSearchResult(row(['courseTitle', 'subjectDescription', 'courseNumber', 'sequenceNumber']))).toBe(true);
  });

  it('still takes them with a column hidden', () => {
    expect(isSearchResult(row(['courseTitle', 'courseNumber']))).toBe(true);
  });

  it("leaves the student's own schedule and plan grids alone", () => {
    // Summary and plan rows fold subject, number and section into Details.
    expect(isSearchResult(row(['courseTitle', 'details', 'courseReferenceNumber']))).toBe(false);
  });
});

const cell = (texts: string[]) => ({
  querySelectorAll: () => texts.map((textContent) => ({ textContent })) as unknown as NodeListOf<Element>,
});

describe('readNames', () => {
  it("reads the instructors' mailto links", () => {
    expect(readNames(cell(['Rachlin, John', ' Smith, Jane ']))).toEqual(['Rachlin, John', 'Smith, Jane']);
  });

  it('says unknown, not nobody, when there are no links to read', () => {
    // [] would make stillTeaching hide a badge our data and Banner agree on.
    expect(readNames(cell([]))).toBeNull();
    expect(stillTeaching('Rachlin, John', readNames(cell([])))).toBe(true);
  });
});
