import { redirect } from 'next/navigation'

// Root lands on /home: the portfolio tracker's Today page (every user).
export default function Home() {
  redirect('/home')
}
