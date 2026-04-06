Show the Signa frontend theming system, i18n, and UI customization.

## Theme System

### 6 Available Themes (`src/lib/themes.ts`)

| ID | Name | Dark? | Primary | Description |
|----|------|-------|---------|-------------|
| `applestocks` | Apple Stocks | Yes | #30D158 | Clean green on dark — default |
| `robinhood` | Robinhood | No | #00C805 | Bright green on white |
| `wealthsimple` | Wealthsimple | No | #2F2F2F | Minimal monochrome |
| `bloomberg` | Bloomberg | Yes | #FF8C21 | Orange terminal aesthetic |
| `webull` | Webull | Yes | #E76F00 | Dark with orange accent |
| `etrade` | E*Trade | No | #6633CC | Purple on light |

### Color Properties
```typescript
colors: {
  bg: string          // Page background
  surface: string     // Card/container background
  surfaceAlt: string  // Alternate surface (hover states, inputs)
  text: string        // Primary text
  textSub: string     // Secondary text
  textHint: string    // Tertiary/muted text
  primary: string     // Brand/accent color
  accent: string      // Secondary accent
  up: string          // Positive (gains, buy)
  down: string        // Negative (losses, sell)
  warning: string     // Caution (hold, volatile)
  border: string      // Borders and dividers
  stripeRisk: string  // High-risk stripe indicator
  stripeSafe: string  // Safe-income stripe indicator
}
```

### Usage Pattern
```tsx
const theme = useTheme()

// Style elements
<div style={{
  backgroundColor: theme.colors.surface,
  color: theme.colors.text,
  border: `1px solid ${theme.colors.border}`
}}>

// Conditional on dark/light
theme.isDark ? theme.colors.text : theme.colors.surface

// Alpha transparency (safe approach)
theme.colors.primary + '15'  // OK for hex colors
// For non-hex safety: check color.startsWith('#') first
```

### Theme Store (`src/store/themeStore.ts`)
```typescript
const setTheme = useThemeStore((s) => s.setTheme)
setTheme('bloomberg')  // Persists to localStorage['signa-theme']
```

### ThemeSwitcher Component
- Grid of color swatches
- Compact mode (pill-sized) and full mode (with labels)
- Check mark on selected theme
- Uses per-swatch theme colors for contrast

## Internationalization (i18n)

### Structure
```
src/lib/i18n/
├── en.json   (250+ keys)
└── pt.json   (250+ keys, Portuguese)
```

### 14 Translation Sections
| Section | Keys | Examples |
|---------|------|---------|
| `app` | 3 | name, title, description |
| `nav` | 10 | overview, signals, watchlist, brain, settings |
| `login` | 15+ | welcome, username, password, OTP prompts, errors |
| `overview` | 20+ | dashboard, stats, quick actions, filters |
| `signals` | 40+ | filters, scan controls, phases, empty states |
| `signal` | 30+ | score, target, sentiment, reasoning, fundamentals |
| `stats` | 8 | gems, win rate, cost, yesterday template |
| `scans` | 5 | schedule, times, status labels |
| `integrations` | 15+ | health, providers, budget |
| `bucket` | 4 | safeIncome, highRisk labels |
| `watchlist` | 5 | add, remove, empty |
| `brain` | 25+ | rules, knowledge, audit, suggestions, unlock |
| `settings` | 15+ | theme, language, providers, save, confirm |
| `error` | 6 | somethingWentWrong, tryAgain, pageNotFound, failedBrainInsights |

### Usage Pattern
```tsx
const t = useI18nStore((s) => s.t)

// Simple string
<p>{t.overview.safeToBuy}</p>

// Template with variables
import { interpolate } from '@/lib/utils'
<p>{interpolate(t.stats.yesterday, { count: stats.gems_yesterday })}</p>
```

### Adding New Keys
1. Add to `src/lib/i18n/en.json` under appropriate section
2. Add Portuguese translation to `src/lib/i18n/pt.json`
3. Access via `t.section.key` — TypeScript will catch missing keys

### Language Store (`src/store/i18nStore.ts`)
```typescript
const setLocale = useI18nStore((s) => s.setLocale)
setLocale('pt')  // Persists to localStorage['signa-lang'] + syncs to backend
```

### LangSwitcher Component
- Toggle button with flag icons
- Persists preference to localStorage
- Syncs to backend via `PUT /health/ai-config`

## Animations & Motion

### Global Rule (`src/app/globals.css`)
```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

### Skeleton Shimmer
- Custom `shimmer` animation defined in globals.css
- Used by Skeleton component for loading states
- Disabled by prefers-reduced-motion

### Transitions
- Buttons: `transition-opacity hover:opacity-80`
- Cards: subtle hover effects via opacity
- Toasts: fade-in/out on mount/unmount
