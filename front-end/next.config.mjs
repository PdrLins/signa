const isDev = process.env.NODE_ENV !== 'production'

// API base baked in at build time (scripts/start.sh / launch.json set
// NEXT_PUBLIC_API_URL). The default is RELATIVE ("/api/v1"): the browser calls
// this Next server, which proxies to the backend (rewrites below). That way a
// phone on the same Wi-Fi reaches everything through http://<mac-ip>:3000
// while the backend itself stays bound to 127.0.0.1.
const apiUrl = process.env.NEXT_PUBLIC_API_URL || '/api/v1'
const apiIsRelative = apiUrl.startsWith('/')
const backendOrigin = process.env.SIGNA_BACKEND_ORIGIN || 'http://127.0.0.1:8000'
const apiOrigin = apiIsRelative ? null : new URL(apiUrl).origin
// Matching WebSocket origin for the log stream (http->ws, https->wss).
const apiWsOrigin = apiOrigin ? apiOrigin.replace(/^http/, 'ws') : null

// 'unsafe-eval' is only needed by the dev server (React Refresh / HMR);
// production bundles don't eval. 'unsafe-inline' stays for Next's inline
// bootstrap scripts (no nonce setup yet).
const scriptSrc = ["'self'", "'unsafe-inline'", ...(isDev ? ["'unsafe-eval'"] : [])]
// connect-src pinned to our own origin + the API origin. Dev additionally
// allows the HMR websocket.
// A relative API is covered by 'self'. The dev HMR socket may come from a
// LAN host (phone), so dev allows any ws: origin.
const connectSrc = ["'self'", ...(apiOrigin ? [apiOrigin, apiWsOrigin] : []), ...(isDev ? ['ws:'] : [])]

// NOTE: the JWT is still kept in localStorage (readable by any XSS).
// Migrating to an HttpOnly, SameSite cookie is a pending follow-up.

/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [{ source: '/api/v1/:path*', destination: `${backendOrigin}/api/v1/:path*` }]
  },
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
