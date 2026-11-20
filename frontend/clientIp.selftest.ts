// Runnable self-check for clientIp (no unit-test framework is installed).
// Run: cd frontend && npm run test:clientip (CI runs it too)
import { trustedClientIp } from './clientIp';

const fails: string[] = [];
const check = (label: string, cond: boolean) => {
  if (!cond) fails.push(label);
  console.log((cond ? 'PASS' : 'FAIL') + ': ' + label);
};
const h = (o: Record<string, string>) => new Headers(o);
const S = 's3cret-value';

check('no Cloudflare: x-real-ip', trustedClientIp(h({ 'x-real-ip': '1.2.3.4' }), undefined) === '1.2.3.4');
check('secret unset: forged cf header ignored',
  trustedClientIp(h({ 'x-real-ip': '1.2.3.4', 'cf-connecting-ip': '9.9.9.9', 'x-rmh-cf-secret': S }), undefined) === '1.2.3.4');
check('cf header without secret ignored',
  trustedClientIp(h({ 'x-real-ip': '1.2.3.4', 'cf-connecting-ip': '9.9.9.9' }), S) === '1.2.3.4');
check('cf header with wrong secret ignored',
  trustedClientIp(h({ 'x-real-ip': '1.2.3.4', 'cf-connecting-ip': '9.9.9.9', 'x-rmh-cf-secret': 'nope' }), S) === '1.2.3.4');
check('cf header with right secret used',
  trustedClientIp(h({ 'x-real-ip': '172.64.0.1', 'cf-connecting-ip': '9.9.9.9', 'x-rmh-cf-secret': S }), S) === '9.9.9.9');
check('IPv6 accepted',
  trustedClientIp(h({ 'x-real-ip': '172.64.0.1', 'cf-connecting-ip': '2001:db8::1', 'x-rmh-cf-secret': S }), S) === '2001:db8::1');
check('garbage cf value falls back',
  trustedClientIp(h({ 'x-real-ip': '1.2.3.4', 'cf-connecting-ip': '1.2.3.4, evil', 'x-rmh-cf-secret': S }), S) === '1.2.3.4');
check('nothing present: null', trustedClientIp(h({}), S) === null);

if (fails.length) { console.error(`\n${fails.length} failed`); process.exit(1); }
console.log('\nall passed');
