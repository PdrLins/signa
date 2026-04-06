# CLAUDE.md — Signa Frontend

Next.js 14 dashboard for Signa investment signal engine. 6 themes, EN/PT bilingual.

## Commands

```bash
npm run dev     # :3000
npm run build   # Production build
npm run lint    # ESLint
```

## Rules (MUST follow)

- **Theme**: All colors from `useTheme()` — NEVER hardcode hex/rgb
- **i18n**: All text from `useI18nStore((s) => s.t)` — NEVER hardcode strings
- **Brain token**: Memory only via brainStore — NEVER save to localStorage
- **Toast**: Global via `useToast()` — NEVER use local toast state
- **API**: All calls through `src/lib/api.ts` — NEVER use raw fetch/axios
- **Memoize**: Wrap computed arrays/objects in `useMemo`, wrap list item components in `React.memo`
- **Accessibility**: All interactive elements need `aria-label`, tabs need ARIA roles
- **Utilities**: Use `src/lib/utils.ts` for shared helpers (formatPrice, interpolate, maskIp) — don't duplicate
- **Timezone**: Use `DEFAULT_TIMEZONE` from `@/lib/utils` — don't hardcode `'America/New_York'`

## Key Behaviors

- Watchlist star toggles add/remove (filled = in watchlist)
- Sentiment bar hidden when `grok_data.confidence === 0`
- Two-pass scan: top 15 get AI reasoning, bottom 35 get "tech-only" label
- Auth: JWT in localStorage + cookie. Middleware guards routes server-side. 401 → /login
- Score fallback: `44/100` format when live price unavailable

## Use `/frontend-*` skills for deep context on each area.
