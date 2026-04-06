Show the Signa frontend architecture and how modules connect.

## Stack
- Next.js 14 (App Router) + TypeScript
- Zustand (state) + React Query (data fetching)
- Axios (HTTP) + WebSocket (logs)
- 6 themes, EN/PT i18n

## File Map

```
src/
├── app/
│   ├── (dashboard)/layout.tsx    → Auth guard, LeftNav, BottomNav wrapper ('use client')
│   ├── (dashboard)/overview/     → Dashboard: StatsBar, QuickActions, top signals, portfolio preview
│   ├── (dashboard)/signals/      → Signal list with 6 filter groups + Scan Now
│   ├── (dashboard)/signals/[ticker]/ → Ticker detail: price chart, fundamentals, reasoning, history
│   ├── (dashboard)/watchlist/    → Add/remove tickers, compact pills + full table
│   ├── (dashboard)/portfolio/    → Manual position tracking (placeholder)
│   ├── (dashboard)/brain/        → Rule/knowledge editor behind OTP 2FA
│   ├── (dashboard)/brain/performance/ → Accuracy metrics
│   ├── (dashboard)/integrations/ → Service health, AI provider status, budget
│   ├── (dashboard)/logs/         → Real-time WebSocket log viewer
│   ├── (dashboard)/settings/     → Theme, language, AI config, logout
│   ├── (dashboard)/how-it-works/ → 21-section guide (6 tabs)
│   ├── login/                    → Two-step: credentials → Telegram OTP
│   ├── providers.tsx             → ErrorBoundary → QueryProvider → StoreInitializer → ThemeApplicator → ToastContainer
│   ├── error.tsx                 → Root error boundary (uses ErrorDisplay)
│   └── not-found.tsx             → 404 page (uses NotFoundDisplay)
├── middleware.ts                 → Server-side auth guard (checks signa-token cookie)
├── components/
│   ├── brain/                    → BrainLocked (OTP), BrainEditor (coordinator), BrainRulesTab, BrainKnowledgeTab, BrainAuditTab, BrainSuggestionsTab, BrainWorkflow
│   ├── charts/                   → PriceChart (recharts, dynamic import), AllocationChart
│   ├── dashboard/                → StatsBar, QuickActions, ScanSchedule, TelegramStatus, DashboardWidgets
│   ├── layout/                   → LeftNav (floating pill), TopNav, BottomNav (mobile), Sidebar
│   ├── signals/                  → SignalCard (memo), SignalList, SignalBadge
│   ├── watchlist/                → WatchlistTable, WatchlistRow (memo)
│   └── ui/                       → Button, Card, Badge, ScoreRing, ProgressBar, SparkLine, StatCard, Skeleton, Toast, ErrorDisplay, LangSwitcher, ThemeSwitcher
├── hooks/                        → useAuth, useBrain (9 hooks), useSignals, useStats, useScans, useWatchlist, usePriceHistory, useTheme, useToast
├── store/                        → authStore (JWT+cookie), brainStore (memory-only token), themeStore, i18nStore, toastStore
├── lib/
│   ├── api.ts                    → Axios client, interceptors, 14 endpoint groups, typed wrappers
│   ├── utils.ts                  → cn, interpolate, formatPrice, maskIp, DEFAULT_TIMEZONE
│   ├── constants.ts              → TOKEN_KEY, THEME_KEY, APP_NAME
│   ├── themes.ts                 → 6 themes: applestocks, robinhood, wealthsimple, bloomberg, webull, etrade
│   └── i18n/                     → en.json + pt.json (250+ keys, 14 sections)
└── types/                        → signal.ts, auth.ts, scan.ts, watchlist.ts, portfolio.ts, chart.ts
```

## Data Flow

```
User Action → Page Component → Hook (React Query) → api.ts (Axios) → Backend API
                                                           ↓
                                                    Response Interceptor
                                                    (401→login, 403→deny, 429→throttle, sanitize errors)
                                                           ↓
                                                    React Query Cache → Component re-render
```

## State Architecture

```
Zustand Stores (client-side):
  authStore   → JWT token + cookie sync + isAuthenticated
  brainStore  → Brain token (memory-only) + auto-expiry setTimeout
  themeStore  → Selected theme ID + localStorage persistence
  i18nStore   → Locale (en/pt) + translation object + backend sync
  toastStore  → Toast queue with auto-dismiss

React Query (server-state cache):
  ['signals', ...filters]  → 2min stale
  ['gems']                 → 5min stale + 5min refetch
  ['stats']                → 60s stale + 60s refetch (paused in background tabs)
  ['scans'], ['scansToday']→ 60s refetch
  ['watchlist']            → default stale (optimistic updates)
  ['brain-*']              → 30s stale (enabled only when unlocked)
  ['price-history', ...]   → 5min stale
```

## Security Layers

1. **middleware.ts** — Server-side cookie check, redirects to /login
2. **api.ts interceptor** — Attaches Bearer token, handles 401/403/429
3. **Brain 2FA** — Separate X-Brain-Token header, memory-only, auto-expiry
4. **CSP headers** — next.config.mjs security headers (X-Frame, CSP, Referrer-Policy)
5. **Error sanitization** — Backend errors stripped of paths/traces before display
6. **IP masking** — Audit log IPs shown as `***.***.***.xxx`

## Provider Stack (wrapping order)

```tsx
<ErrorBoundary>
  <QueryProvider defaultOptions={{ queries: { staleTime: 30s, retry: 1 } }}>
    <StoreInitializer />  {/* Reads localStorage → hydrates auth, theme, i18n */}
    <ThemeApplicator>     {/* Sets CSS vars + body background */}
      <ToastContainer />  {/* Global toast overlay */}
      {children}
    </ThemeApplicator>
  </QueryProvider>
</ErrorBoundary>
```
