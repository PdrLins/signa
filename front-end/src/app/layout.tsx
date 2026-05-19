import type { Metadata } from 'next'
import localFont from 'next/font/local'
import { JetBrains_Mono } from 'next/font/google'
import './globals.css'
import { Providers } from './providers'

const geistSans = localFont({
  src: './fonts/GeistVF.woff',
  variable: '--font-geist-sans',
  weight: '100 900',
})

// Day 32 revamp: dropped serif (Newsreader/Instrument). Pedro found it
// clashed with the rest of the design — going pure sans for everything,
// mono only for numeric data. Hierarchy comes from weight + size, not
// from a font-family switch.
const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  variable: '--font-mono',
  display: 'swap',
})

export const metadata: Metadata = {
  title: 'Signa — AI Signal Engine',
  description: 'AI-powered stock signal engine scanning TSX, NYSE, and NASDAQ',
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${geistSans.variable} ${jetbrainsMono.variable} font-sans antialiased`}>
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
