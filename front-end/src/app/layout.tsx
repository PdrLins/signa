import type { Metadata } from 'next'
import localFont from 'next/font/local'
import { Newsreader, JetBrains_Mono } from 'next/font/google'
import './globals.css'
import { Providers } from './providers'

const geistSans = localFont({
  src: './fonts/GeistVF.woff',
  variable: '--font-geist-sans',
  weight: '100 900',
})

// Day 32 revamp: editorial typography pairing. Newsreader (serif) for
// display headers + ticker symbols — gives the "FT/Stripe Press" feel.
// JetBrains Mono for all numeric data — gives Bloomberg-Terminal density
// without the cold-blue cliché. Both loaded via next/font/google for
// automatic preload + zero-CLS.
const newsreader = Newsreader({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  style: ['normal', 'italic'],
  variable: '--font-serif',
  display: 'swap',
})

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
      <body className={`${geistSans.variable} ${newsreader.variable} ${jetbrainsMono.variable} font-sans antialiased`}>
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
