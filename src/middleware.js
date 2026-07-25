import { next } from '@vercel/functions';

const COOKIE_NAME = 'rancho_portal_session';

function cookieValue(request, name) {
  const raw = request.headers.get('cookie') || '';
  for (const part of raw.split(';')) {
    const separator = part.indexOf('=');
    if (separator < 0) continue;
    if (part.slice(0, separator).trim() === name) {
      return part.slice(separator + 1).trim();
    }
  }
  return '';
}

function constantTimeEqual(left, right) {
  if (left.length !== right.length) return false;
  let mismatch = 0;
  for (let index = 0; index < left.length; index += 1) {
    mismatch |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return mismatch === 0;
}

async function signature(expiresAt, secret) {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    'raw',
    encoder.encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  const signed = await crypto.subtle.sign('HMAC', key, encoder.encode(expiresAt));
  return Array.from(new Uint8Array(signed), (value) => value.toString(16).padStart(2, '0')).join('');
}

async function hasValidSession(request) {
  const secret = process.env.PORTAL_SESSION_SECRET || '';
  const token = cookieValue(request, COOKIE_NAME);
  const separator = token.indexOf('.');
  if (!secret || separator < 1) return false;
  const expiresAt = token.slice(0, separator);
  const supplied = token.slice(separator + 1);
  if (!/^\d+$/.test(expiresAt) || Number(expiresAt) <= Math.floor(Date.now() / 1000)) {
    return false;
  }
  return constantTimeEqual(supplied, await signature(expiresAt, secret));
}

export default async function portalDataGuard(request) {
  if (await hasValidSession(request)) {
    return next({
      headers: {
        'Cache-Control': 'private, no-store',
        'X-Content-Type-Options': 'nosniff',
      },
    });
  }
  return new Response(
    JSON.stringify({ status: 'error', error: 'authentication_required' }),
    {
      status: 401,
      headers: {
        'Content-Type': 'application/json; charset=utf-8',
        'Cache-Control': 'no-store',
        'X-Content-Type-Options': 'nosniff',
      },
    },
  );
}

export const config = {
  matcher: ['/data/:path*', '/reports/:path*', '/img/:path*', '/og-expansion.png'],
};
