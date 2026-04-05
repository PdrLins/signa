# CLAUDE.md — Signa Frontend

Next.js 14 dashboard for the Signa investment signal engine. Displays signals, scans, watchlist, brain editor, and settings with 6 themes and bilingual support (EN/PT).

## Commands

```bash
cd front-end
npm run dev     # Development server on :3000
npm run build   # Production build
npm run lint    # ESLint check
```

## Structure

```
front-end/src/
├── app/
│   ├── (dashboard)/          → Protected layout with floating left nav
│   │   ├── overview/         → Dashboard: stats, quick actions, top signals
│   │   ├── signals/          → Signal list with filters + Scan Now button
│   │   ├── signals/[ticker]/ → Ticker detail page (dynamic)
│   │   ├── watchlist/        → Watchlist management
│   │   ├── portfolio/        → Portfolio (placeholder)
│   │   ├── brain/            → Brain editor (locked/unlocked states)
│   │   ├── how-it-works/     → Guide page (21 sections)
│   │   └── settings/         → Theme, language, AI providers, logout
│   ├── login/                → Two-step auth (credentials + OTP)
│   └── providers.tsx         → QueryProvider, theme, auth, i18n, toast
├── components/
│   ├── brain/                → BrainLocked, BrainEditor, BrainWorkflow
│   ├── dashboard/            → StatsBar, QuickActions, ScanSchedule, etc.
│   ├── signals/              → SignalCard, SignalList
│   ├── layout/               → LeftNav (floating), BottomNav, Sidebar
│   └── ui/                   → Card, Button, Badge, ScoreRing, Toast, etc.
├── hooks/                    → useSignals, useStats, useScans, useBrain, etc.
├── store/                    → Zustand: authStore, themeStore, i18nStore, brainStore
├── lib/
│   ├── api.ts                → Axios client with auth interceptor
│   ├── i18n/                 → en.json + pt.json (250+ translation keys)
│   └── themes.ts             → 6 theme definitions
└── types/                    → TypeScript interfaces
```

## Key Patterns

- **Theme**: All colors from `useTheme()` — never hardcode colors
- **i18n**: All text from `useI18nStore((s) => s.t)` — never hardcode strings
- **Auth**: JWT stored in localStorage via authStore. 401 → redirect to /login
- **Brain token**: Memory only (never localStorage). Refresh = re-auth required
- **Toast**: Global system via `useToast()` — never use local toast state
- **API**: All calls through `src/lib/api.ts` with typed response interfaces

## Important Rules

- Brain token is session-only — NEVER save to localStorage
- Watchlist star toggles add/remove (filled = in watchlist)
- Sentiment bar hidden when `grok_data.confidence === 0` (fallback data)
- Score fallback shows `44/100` format when live price unavailable
- Two-pass scan: top 15 get AI reasoning, bottom 35 get "tech-only" label
