const isDev = process.env.NODE_ENV !== 'production'

// API origin baked in at build time (scripts/start.sh sets NEXT_PUBLIC_API_URL).
const apiOrigin = new URL(process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1').origin
// Matching WebSocket origin for the log stream (http->ws, https->wss).
const apiWsOrigin = apiOrigin.replace(/^http/, 'ws')

// 'unsafe-eval' is only needed by the dev server (React Refresh / HMR);
// production bundles don't eval. 'unsafe-inline' stays for Next's inline
// bootstrap scripts (no nonce setup yet).
const scriptSrc = ["'self'", "'unsafe-inline'", ...(isDev ? ["'unsafe-eval'"] : [])]
// connect-src pinned to our own origin + the API origin. Dev additionally
// allows the HMR websocket.
const connectSrc = ["'self'", apiOrigin, apiWsOrigin, ...(isDev ? ['ws://localhost:*', 'ws://127.0.0.1:*'] : [])]

// NOTE: the JWT is still kept in localStorage (readable by any XSS).
// Migrating to an HttpOnly, SameSite cookie is a pending follow-up.

/** @type {import('next').NextConfig} */
const nextConfig = {
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          { key: 'X-DNS-Prefetch-Control', value: 'on' },
          { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
          {
            key: 'Content-Security-Policy',
            value: [
              "default-src 'self'",
              `script-src ${scriptSrc.join(' ')}`,
              "style-src 'self' 'unsafe-inline'",
              "img-src 'self' data: blob: https:",
              "font-src 'self' data:",
              `connect-src ${connectSrc.join(' ')}`,
              "frame-ancestors 'none'",
              "base-uri 'self'",
              "form-action 'self'",
              "object-src 'none'",
            ].join('; '),
          },
        ],
      },
    ]
  },
};

export default nextConfig;
