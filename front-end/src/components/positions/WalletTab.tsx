'use client'

import { WalletCard } from './WalletCard'
import { WalletHistory } from './WalletHistory'

export function WalletTab() {
  return (
    <div className="space-y-6">
      {/* Wallet card (Day 15) — self-fetches its own slice so
          deposit/withdraw refreshes it instantly without waiting on
          the full virtual-portfolio summary. */}
      <WalletCard />

      {/* Transactions ledger — collapsed by default. Click to see
          every deposit, buy, sell, legacy liquidation, etc. */}
      <WalletHistory />
    </div>
  )
}
