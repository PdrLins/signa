import { redirect } from 'next/navigation'

// Day 32 revamp: root redirects to /brain/performance (the page actually used)
// instead of /overview (which had become a low-information landing). One
// place change makes the daily experience match daily usage.
export default function Home() {
  redirect('/brain/performance')
}
