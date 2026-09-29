import { redirect } from 'next/navigation'

// The old "Portfolio (coming soon)" page is now My holdings.
export default function PortfolioPage() {
  redirect('/holdings')
}
