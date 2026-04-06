Show the Signa frontend component library, UI patterns, and how to build new features.

## UI Components (`src/components/ui/`)

### Button
```tsx
<Button variant="primary" | "secondary" | "ghost" disabled={false} onClick={fn}>
  Text
</Button>
```
- Variants: primary (theme.colors.primary bg), secondary (surfaceAlt bg), ghost (transparent)
- Auto `aria-disabled` when disabled
- Text color: `theme.colors.surface` for primary, `theme.colors.text` for others

### Card
```tsx
<Card onClick={fn}>  {/* Optional click handler */}
  Content
</Card>
```
- Surface background with subtle border and shadow
- Rounded corners, padding included

### Badge
```tsx
<Badge variant="buy" | "sell" | "hold" | "avoid" | "gem" | "info">
  BUY
</Badge>
```
- Color-coded: buy=up, sell=down, hold=warning, avoid=down, gem=primary

### ScoreRing
```tsx
<ScoreRing score={85} size={48} />
```
- SVG circular progress ring
- Color: >=80 green, >=60 yellow, <60 red
- Always shows numeric score (colorblind safe)
- Has `role="img"` and `aria-label`

### Skeleton
```tsx
<Skeleton width={200} height={20} borderRadius={8} />
```
- Shimmer animation (respects prefers-reduced-motion)
- Use in loading.tsx files and isLoading guards

### ProgressBar
```tsx
<ProgressBar value={65} max={100} color={theme.colors.primary} />
```
- Clamped 0-100, rounded corners

### SparkLine
```tsx
<SparkLine points={[1,2,3,4]} trend="up" | "down" width={60} height={20} />
```
- SVG with gradient fill
- Uses `useId()` for unique gradient IDs

### ErrorDisplay / NotFoundDisplay
```tsx
<ErrorDisplay message="Something failed" onRetry={() => reset()} fullScreen />
<NotFoundDisplay />
```
- Theme-aware, i18n strings, centered layout

### Toast (via hook, not component)
```tsx
const toast = useToast()
toast.show('Saved!', 'success', 3000)
toast.show('Failed to save', 'error')
```
- Variants: success, error, warning, info
- Auto-dismiss (default 4s), manual close button
- `role="alert"` for errors, `role="status"` for others

## Signal Components (`src/components/signals/`)

### SignalCard (React.memo)
```tsx
<SignalCard signal={signal} defaultExpanded={false} isTopPick={false} />
```
- Expandable card with score ring, action badge, price, target
- Expanded view: reasoning, sentiment bar, catalyst, entry window
- Watchlist star toggle inline
- `role="button"`, `aria-expanded`, keyboard accessible

### SignalList
```tsx
<SignalList signals={signals} isLoading={bool} isError={bool} error={Error} topPickId={string} emptyMessage={string} />
```
- Handles loading (skeleton), error, and empty states
- Maps signals to SignalCard

## Dashboard Components (`src/components/dashboard/`)

### StatsBar
- Shows gems today/yesterday, win rate, tickers scanned, AI cost
- Uses `interpolate()` for template strings
- Skeleton loading state

### QuickActions
- Two columns: "Safe to Buy" (BUY signals, low risk) and "Consider Selling" (SELL/AVOID/WEAKENING)
- Sorted by risk level then score
- Memoized filtering with `useMemo`

### ScanSchedule
- Shows today's 4 scan slots with status colors
- Data from `useScansToday()` hook

## Brain Components (`src/components/brain/`)

### Flow: BrainLocked → BrainEditor

**BrainLocked**: Lock screen with OTP form
- Challenge → Telegram sends OTP → 6-digit input → Verify → Unlock
- Auto-submit on 6 digits, paste support
- Countdown timer, 3 attempts before reset

**BrainEditor**: Coordinator (170 lines)
- 5 tabs: Workflow, Rules, Knowledge, Suggestions, Audit
- Tab components: BrainRulesTab, BrainKnowledgeTab, BrainSuggestionsTab, BrainAuditTab
- Timer component shows remaining brain token seconds
- Lock button to manually expire session

### Tab Props Pattern
```tsx
<BrainRulesTab
  rules={rulesList}           // useMemo'd Record<string, unknown>[]
  isLoading={rulesLoading}
  ruleFilter={ruleFilter}
  onRuleFilterChange={setRuleFilter}
  onRuleSave={handleRuleSave}
/>
```

## Chart Components (`src/components/charts/`)

### PriceChart (React.memo)
```tsx
<PriceChart symbol="AAPL" />
```
- Dynamic import of recharts (code splitting)
- Time range selector: 1D, 1W, 1M, 3M
- Uses `usePriceHistory` hook

## Layout Components

### LeftNav (floating pill)
- Fixed left sidebar, icon-only navigation
- Active route highlighted
- z-50 positioning

### BottomNav (mobile)
- Fixed bottom bar for mobile viewport
- Safe area inset support
- Blur backdrop

### Sidebar (desktop right panel)
- Watchlist compact view + widgets
- Shown on wider screens alongside main content

## Building a New Page

1. Create `src/app/(dashboard)/[feature]/page.tsx` with `'use client'`
2. Create `src/app/(dashboard)/[feature]/loading.tsx` with Skeleton layout
3. Add navigation item to `src/components/layout/LeftNav.tsx` NAV_ITEMS
4. Add translation keys to both `en.json` and `pt.json`
5. Create hooks in `src/hooks/use[Feature].ts` wrapping React Query
6. Add API endpoints to `src/lib/api.ts` with typed interfaces
7. Add types to `src/types/[feature].ts`
8. Use `useTheme()` for all colors, `useI18nStore` for all text
9. Handle loading, error, and empty states
