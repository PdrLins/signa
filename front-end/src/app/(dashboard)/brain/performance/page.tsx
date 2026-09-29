import { redirect } from 'next/navigation'

// The brain performance page moved to /positions (tabbed: Positions,
// Trade history, Wallet). Kept as a redirect for old bookmarks.
export default function BrainPerformanceRedirect() {
  redirect('/positions')
}
