// Every score on the payload is nullable. A professor with no ratings renders
// a dash rather than "null" or a misleading 0.

export function score(n: number | null): string {
  return n == null ? '—' : n.toFixed(1);
}

export function percent(n: number | null): string {
  return n == null ? '—' : `${Math.round(n)}%`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return n === 1 ? one : many;
}
