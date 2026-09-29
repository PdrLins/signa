import { redirect } from 'next/navigation'

// Root lands on /today: the scan funnel, today's decisions and open
// positions at a glance.
export default function Home() {
  redirect('/today')
}
