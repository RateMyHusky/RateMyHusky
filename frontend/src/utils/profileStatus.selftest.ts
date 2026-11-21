// Runnable self-check for profileStatus (no unit-test framework is installed).
// Run: cd frontend && npx tsx src/utils/profileStatus.selftest.ts
// Prints PASS/FAIL per check and exits non-zero on any failure.
import { argv } from 'node:process';
import { fileURLToPath } from 'node:url';
import { getProfileStatus, markProfileSaved, onProfileSaved } from './profileStatus';

function setToken(token: string | null) {
  (globalThis as unknown as { localStorage: unknown }).localStorage = {
    getItem: (k: string) => (k === 'auth_token' ? token : null),
  };
}

async function selftest(): Promise<number> {
  const fails: string[] = [];
  const check = (label: string, cond: boolean) => {
    if (!cond) fails.push(label);
    console.log((cond ? 'PASS' : 'FAIL') + ': ' + label);
  };
  let calls = 0;
  const ok = async () => { calls++; return { exists: false, optedOut: false }; };

  setToken(null);
  check('no token gives null', (await getProfileStatus(ok)) === null && calls === 0);

  setToken('a');
  const first = await getProfileStatus(ok);
  const second = await getProfileStatus(ok);
  check('cached per token (same token fetches once)', calls === 1 && first === second && first?.exists === false);
  setToken('b');
  await getProfileStatus(ok);
  check('cached per token (new token fetches again)', calls === 2);

  setToken('c');
  calls = 0;
  const bad = async () => { throw new Error('down'); };
  const failed = await getProfileStatus(bad);
  const retried = await getProfileStatus(ok);
  check('failure is not cached', failed === null && calls === 1 && retried?.exists === false);

  setToken('d');
  await getProfileStatus(ok);
  calls = 0;
  markProfileSaved();
  const saved = await getProfileStatus(ok);
  check('markProfileSaved', calls === 0 && saved?.exists === true && saved.optedOut === false);

  let heard = 0;
  const off = onProfileSaved(() => { heard++; });
  markProfileSaved();
  off();
  markProfileSaved();
  check('onProfileSaved notifies until unsubscribed', heard === 1);

  console.log(fails.length ? `${fails.length} FAIL(s): ` + fails.join(', ') : 'ALL PASS');
  return fails.length ? 1 : 0;
}

if (argv[1] && fileURLToPath(import.meta.url) === argv[1]) {
  selftest().then((code) => process.exit(code));
}
