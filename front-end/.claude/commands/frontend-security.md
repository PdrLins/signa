Show the Signa frontend security architecture.

## Authentication Flow

```
1. POST /auth/login { username, password }
   → Returns session_token (short-lived)

2. Telegram bot sends OTP to user's chat

3. POST /auth/verify-otp { session_token, otp_code }
   → Returns access_token (JWT)

4. authStore.setToken(access_token)
   → Saves to localStorage['signa-token']
   → Saves to cookie 'signa-token' (SameSite=Strict, max-age=86400)
   → Sets isAuthenticated = true
```

## Route Protection (Two Layers)

### Layer 1: Server-side Middleware (`src/middleware.ts`)
- Runs on EVERY request before page renders
- Checks for `signa-token` cookie
- Redirects to `/login?redirect={path}` if missing
- Public paths: `/login`, `/api`, `/favicon.ico`
- Static assets excluded via `config.matcher`

### Layer 2: Client-side Layout (`src/app/(dashboard)/layout.tsx`)
- Reads localStorage token on mount
- Redirects to `/login` if no token and not authenticated
- Hydrates auth store from localStorage

## Token Management

### Access Token (JWT)
- Stored: localStorage + cookie (dual storage)
- Cookie: `SameSite=Strict; path=/; max-age=86400`
- Attached: `Authorization: Bearer {token}` via axios interceptor
- Cleared on: 401 response, manual logout
- Both localStorage AND cookie cleared on logout/401

### Brain Token (Elevated Access)
- Stored: **Memory only** (Zustand brainStore) — NEVER persisted
- Expires: Auto via `setTimeout(lock, expiresIn * 1000)`
- Attached: `X-Brain-Token` header (manually, not via interceptor)
- Lost on: Page refresh, tab close, manual lock, timeout
- Requires: Fresh OTP to re-acquire

## API Security

### Request Interceptor (`src/lib/api.ts`)
- Auto-attaches Bearer token for non-public routes
- Public routes identified by `.startsWith()` prefix match
- Missing token on protected route → immediate redirect to `/login`

### Response Interceptor
- **401**: Clears token (localStorage + cookie) → redirects to `/login`
- **403**: Throws "Access denied" (sanitized)
- **429**: Throws "Too many requests — please wait"
- **5xx**: Throws generic "Something went wrong"
- **4xx**: Sanitizes error detail — strips file paths, stack traces, caps at 300 chars
- **Network error**: "Network error — please check your connection"

### Error Sanitization (`sanitizeErrorMessage()`)
```typescript
// Strips paths like /app/, /usr/, /home/, /node_modules/
// Strips "Traceback" and "File " patterns
// Truncates to 300 chars
// 5xx always returns generic message
```

## WebSocket Security
- Log streaming uses `Sec-WebSocket-Protocol` header for brain token
- NOT passed as URL query parameter (prevents server log/browser history leaks)
- Connection: `new WebSocket(url, ['brain-token.' + brainToken])`

## CSP & Headers (`next.config.mjs`)

```
Content-Security-Policy:
  default-src 'self'
  script-src 'self' 'unsafe-eval' 'unsafe-inline'
  style-src 'self' 'unsafe-inline'
  img-src 'self' data: blob: https:
  font-src 'self' data:
  connect-src 'self' ws: wss: {API_ORIGIN}
  frame-ancestors 'none'

X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
X-DNS-Prefetch-Control: on
```

## Client-Side Protections

| Protection | Implementation |
|-----------|---------------|
| XSS (token theft) | Token in httpOnly-like cookie for middleware; localStorage for client use |
| IP masking | `maskIp()` in logs and audit displays |
| OTP brute force | 3 attempts client-side, countdown timer (server enforces real limit) |
| Double-click mutations | `disabled={mutation.isPending}` on all mutation buttons |
| Settings changes | Inline confirmation dialog before saving sensitive config |
| Brain token leak | Memory-only storage, auto-expiry, manual lock button |
| Error info disclosure | `sanitizeErrorMessage()` strips paths, traces, internal details |
| Reduced motion | `@media (prefers-reduced-motion)` disables all animations |

## Brain 2FA Flow

```
1. User clicks "Unlock Brain"
2. POST /brain/challenge → Telegram sends OTP
3. User enters 6-digit OTP
4. POST /brain/verify { otp } → brain_token (60s expiry typical)
5. brainStore.setBrainToken(token, expiresIn)
   → setTimeout(lock, expiresIn * 1000)
6. All brain API calls include X-Brain-Token header
7. On expiry/refresh/lock → must re-authenticate
```

## Environment Variables
- `NEXT_PUBLIC_API_URL` — Backend API base (exposed in client bundle by design)
- `NEXT_PUBLIC_SUPABASE_URL` — Unused placeholder
- `NEXT_PUBLIC_SUPABASE_ANON_KEY` — Unused placeholder
