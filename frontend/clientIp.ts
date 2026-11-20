// Which IP the middleware reports to the backend as the student's.
//
// Without Cloudflare in front, Vercel sets x-real-ip to the student's address. Behind
// Cloudflare, x-real-ip is a Cloudflare edge address and the student's is in
// CF-Connecting-IP. Anyone can send that header straight to a *.vercel.app host, so it is
// believed only when the request also carries CF_SHARED_SECRET in x-rmh-cf-secret, which
// a Cloudflare Transform Rule adds (see frontend/CLOUDFLARE_FRONTING.md). Otherwise it is
// ignored and x-real-ip is used, exactly as before.
// Run the selftest: cd frontend && npm run test:clientip

const IP_RE = /^[0-9a-fA-F:.]{3,45}$/;

function constantTimeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export function trustedClientIp(headers: Headers, cfSecret: string | undefined): string | null {
  const cf = headers.get('cf-connecting-ip');
  const sent = headers.get('x-rmh-cf-secret');
  if (cfSecret && cf && sent && constantTimeEqual(cfSecret, sent) && IP_RE.test(cf)) return cf;
  return headers.get('x-real-ip');
}
