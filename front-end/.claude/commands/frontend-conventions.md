Show the coding conventions and patterns for Signa frontend.

## Language & Style
- TypeScript strict mode, Next.js 14 App Router
- `'use client'` on all interactive components (pages, forms, anything with hooks)
- Functional components only, no class components
- Named exports for components, default exports for pages

## Theme Pattern
- NEVER hardcode colors — always `const theme = useTheme()` then `theme.colors.text`, `theme.colors.primary`, etc.
- Theme colors available: `bg, surface, surfaceAlt, text, textSub, textHint, primary, accent, up, down, warning, border, stripeRisk, stripeSafe`
- Theme has `isDark` boolean for conditional dark/light logic
- For alpha transparency on hex colors: check `color.startsWith('#')` before appending alpha suffix

## i18n Pattern
- NEVER hardcode user-facing strings — always `const t = useI18nStore((s) => s.t)` then `t.section.key`
- Translation keys in `src/lib/i18n/en.json` and `pt.json`
- For template strings with variables: use `interpolate(t.stats.yesterday, { count: 5 })` from `@/lib/utils`
- When adding new UI text: add keys to BOTH en.json and pt.json

## Data Fetching Pattern
- All API calls go through `src/lib/api.ts` typed wrappers (e.g., `signalsApi.getAll()`, `watchlistApi.add()`)
- Hooks in `src/hooks/` wrap React Query: `useQuery` for reads, `useMutation` for writes
- Always set `staleTime` on queries (default 2min for signals, 5min for prices, 30s for brain)
- Use `refetchIntervalInBackground: false` on polling queries
- For optimistic updates: use `onMutate` → cancel queries → snapshot → apply optimistic → `onError` rollback

## State Management
- Zustand stores in `src/store/` for client-only state (auth, theme, i18n, brain token, toasts)
- React Query for server state — never duplicate API data in Zustand
- Brain token is MEMORY-ONLY (brainStore) — never persist to localStorage
- Auth token syncs to both localStorage AND cookie (for middleware)

## Component Patterns
- Wrap list item components in `React.memo()`: SignalCard, WatchlistRow, LogLine, PriceChart
- Wrap expensive computations in `useMemo` with specific scalar deps (not entire objects)
- Use `useCallback` for handlers passed as props to memoized children
- Toast notifications via `useToast().show(message, variant, duration?)` — never local toast state
- Disable mutation buttons with `disabled={mutation.isPending}` to prevent double-clicks
- For debounced inputs: `useState` for immediate value + `useEffect` with `setTimeout` for debounced value

## API Layer Rules
- All endpoints defined in `src/lib/api.ts` with typed request/response interfaces
- Brain API calls must include `X-Brain-Token` header via `brainStore.getHeaders()`
- Public routes (no auth needed): `/auth/login`, `/auth/verify-otp`, `/health`
- Use axios `params` for query params — never template string interpolation in URLs
- AbortController available via `createAbortableRequest()` from api.ts

## Accessibility Requirements
- All icon-only buttons need `aria-label`
- Tab navigation needs `role="tablist"`, `role="tab"` with `aria-selected`, `role="tabpanel"` with `aria-controls`/`aria-labelledby`
- Filter buttons need `aria-pressed={isActive}`
- Toast containers need `role="alert"` (errors) or `role="status"` (info/success)
- Expandable cards need `aria-expanded`, `tabIndex={0}`, keyboard Enter/Space handler
- Score indicators must not rely on color alone (always show numeric value)
- Global `prefers-reduced-motion` rule in globals.css disables animations

## File Organization
- Pages in `src/app/(dashboard)/[feature]/page.tsx`
- Feature components co-located: `src/components/[feature]/`
- Shared UI in `src/components/ui/`
- One hook file per domain in `src/hooks/`
- Types in `src/types/` (not inline in api.ts or components)
- Shared utilities in `src/lib/utils.ts` — don't create local helpers that duplicate these

## Utilities Available (`@/lib/utils`)
- `cn(...inputs)` — clsx + tailwind-merge
- `interpolate(template, { key: value })` — i18n placeholder replacement
- `formatPrice(v: number | null | undefined)` — `$X.XX` or `--`
- `maskIp(text)` — mask IPv4 to `***.***.***.xxx`
- `DEFAULT_TIMEZONE` — `'America/New_York'` constant

## Error Handling
- Route-level: `error.tsx` files with `ErrorDisplay` component
- Route-level: `loading.tsx` files with `Skeleton` components
- Query-level: check `isError` from useQuery, show inline error in a Card
- Mutation-level: `try/catch` with `toast.show(err.message, 'error')`
- API-level: interceptor sanitizes errors (strips paths, stack traces, caps 300 chars)

## Security Rules
- Never expose raw backend error messages — sanitized by api.ts interceptor
- Mask IP addresses in UI with `maskIp()` from utils
- Brain token auto-expires via `setTimeout` — never extend manually
- Settings changes require inline confirmation dialog before save
- WebSocket auth uses subprotocol header, not URL query params
