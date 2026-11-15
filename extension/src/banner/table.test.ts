import { describe, expect, it } from 'vitest';
import { stillTeaching } from './table';

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
