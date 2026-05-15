export type ThemeId =
  | 'slate'
  | 'applestocks'
  | 'robinhood'
  | 'wealthsimple'
  | 'bloomberg'
  | 'webull'
  | 'etrade'

export interface Theme {
  id: ThemeId
  name: string
  description: string
  isDark: boolean
  colors: {
    // Backgrounds
    bg: string
    surface: string
    surfaceAlt: string
    nav: string
    navActive: string

    // Text
    text: string
    textSub: string
    textHint: string

    // Brand
    primary: string
    accent: string

    // Semantic
    up: string
    down: string
    warning: string

    // Borders
    border: string

    // Signal stripe gradients
    stripeRisk: string
    stripeSafe: string
  }
}

export const themes: Record<ThemeId, Theme> = {
  // Day 32 revamp: Linear / Mercury Bank inspired professional dark.
  // Near-black slate, cool muted off-white, single-accent slate-blue.
  // Up/down separated by HUE not red/green — wins are cool blue (calm),
  // losses are drained slate gray. Reads as institutional/private-banking
  // rather than retail-trader. References:
  // - https://linear.app
  // - https://mercury.com/insights
  slate: {
    id: 'slate',
    name: 'Slate',
    description: 'Near-black slate + muted blue. Professional, no green/red.',
    isDark: true,
    colors: {
      bg: '#0E1116',          // Linear-style near-black with slight blue undertone
      surface: '#161B22',     // cards (GitHub-dark surface tone)
      surfaceAlt: '#1C2128',  // nested / hover
      nav: '#0B0E13',         // nav darker than bg for separation
      navActive: '#1C2128',
      text: '#E6EAF0',        // cool off-white
      textSub: '#7B8590',     // cool gray
      textHint: '#4A535E',
      primary: '#6B8FBC',     // muted slate-blue — institutional
      accent: '#85A3CC',      // brighter slate-blue for hover/active
      // Semantic — the headline of this theme:
      up: '#7FB3D5',          // cool desaturated blue (calm win, not loud green)
      down: '#6E7681',        // drained slate gray (muted loss, not aggressive red)
      warning: '#C9A961',     // subdued amber kept for warnings only
      border: 'rgba(140, 160, 200, 0.10)',  // subtle blue-tinted divider
      stripeRisk: 'linear-gradient(90deg, #6B8FBC, #85A3CC)',
      stripeSafe: 'linear-gradient(90deg, #4A6F94, #6B8FBC)',
    },
  },
  applestocks: {
    id: 'applestocks',
    name: 'Apple Stocks',
    description: 'iOS system colors — clean and familiar',
    isDark: false,
    colors: {
      bg: '#F2F2F7',
      surface: '#FFFFFF',
      surfaceAlt: '#F9F9FB',
      nav: '#E5E5EA',
      navActive: '#FFFFFF',
      text: '#1C1C1E',
      textSub: '#8E8E93',
      textHint: '#C7C7CC',
      primary: '#007AFF',
      accent: '#5856D6',
      up: '#34C759',
      down: '#FF3B30',
      warning: '#FF9500',
      border: 'rgba(0,0,0,0.08)',
      stripeRisk: 'linear-gradient(90deg, #007AFF, #5856D6)',
      stripeSafe: 'linear-gradient(90deg, #34C759, #30D158)',
    },
  },
  robinhood: {
    id: 'robinhood',
    name: 'Robinhood',
    description: 'White and green — bold and optimistic',
    isDark: false,
    colors: {
      bg: '#FFFFFF',
      surface: '#F5F5F5',
      surfaceAlt: '#EBEBEB',
      nav: '#F0F0F0',
      navActive: '#FFFFFF',
      text: '#1A1A1A',
      textSub: '#8A8A8A',
      textHint: '#BBBBBB',
      primary: '#00C805',
      accent: '#00A804',
      up: '#00C805',
      down: '#FF5000',
      warning: '#FFB800',
      border: 'rgba(0,0,0,0.08)',
      stripeRisk: 'linear-gradient(90deg, #00C805, #00A804)',
      stripeSafe: 'linear-gradient(90deg, #00C805, #00D606)',
    },
  },
  wealthsimple: {
    id: 'wealthsimple',
    name: 'Wealthsimple',
    description: 'Off-white with orange — approachable',
    isDark: false,
    colors: {
      bg: '#F7F7F5',
      surface: '#FFFFFF',
      surfaceAlt: '#F2F2F0',
      nav: '#EEEEEB',
      navActive: '#FFFFFF',
      text: '#1C1C1C',
      textSub: '#888882',
      textHint: '#BBBBBA',
      primary: '#FF6B00',
      accent: '#FF8C00',
      up: '#00A650',
      down: '#E8192C',
      warning: '#FF9900',
      border: 'rgba(0,0,0,0.07)',
      stripeRisk: 'linear-gradient(90deg, #FF6B00, #FF8C00)',
      stripeSafe: 'linear-gradient(90deg, #00A650, #00C85A)',
    },
  },
  bloomberg: {
    id: 'bloomberg',
    name: 'Bloomberg',
    description: 'Dark terminal — professional and sharp',
    isDark: true,
    colors: {
      bg: '#111111',
      surface: '#1E1E1E',
      surfaceAlt: '#2A2A2A',
      nav: '#1E1E1E',
      navActive: '#2A2A2A',
      text: '#FFFFFF',
      textSub: '#999999',
      textHint: '#555555',
      primary: '#F5A623',
      accent: '#F7B944',
      up: '#00D964',
      down: '#FF3B3B',
      warning: '#F5A623',
      border: 'rgba(255,255,255,0.08)',
      stripeRisk: 'linear-gradient(90deg, #F5A623, #F7B944)',
      stripeSafe: 'linear-gradient(90deg, #00D964, #00F070)',
    },
  },
  webull: {
    id: 'webull',
    name: 'Webull',
    description: 'Dark navy with teal — advanced trader',
    isDark: true,
    colors: {
      bg: '#131722',
      surface: '#1E2130',
      surfaceAlt: '#252B3B',
      nav: '#1E2130',
      navActive: '#2A2F45',
      text: '#D1D4DC',
      textSub: '#787B86',
      textHint: '#434651',
      primary: '#00B2A3',
      accent: '#26A69A',
      up: '#26A69A',
      down: '#EF5350',
      warning: '#FF9800',
      border: 'rgba(255,255,255,0.07)',
      stripeRisk: 'linear-gradient(90deg, #00B2A3, #26A69A)',
      stripeSafe: 'linear-gradient(90deg, #26A69A, #2EBD85)',
    },
  },
  etrade: {
    id: 'etrade',
    name: 'E*Trade',
    description: 'Purple on white — institutional trust',
    isDark: false,
    colors: {
      bg: '#F4F2F8',
      surface: '#FFFFFF',
      surfaceAlt: '#F0EEF6',
      nav: '#EDE9F5',
      navActive: '#FFFFFF',
      text: '#1A1A2E',
      textSub: '#78909C',
      textHint: '#B0BEC5',
      primary: '#6B2D8B',
      accent: '#8B44AD',
      up: '#2E7D32',
      down: '#C62828',
      warning: '#EF6C00',
      border: 'rgba(0,0,0,0.08)',
      stripeRisk: 'linear-gradient(90deg, #6B2D8B, #8B44AD)',
      stripeSafe: 'linear-gradient(90deg, #2E7D32, #388E3C)',
    },
  },
}

export const DEFAULT_THEME: ThemeId = 'slate'
