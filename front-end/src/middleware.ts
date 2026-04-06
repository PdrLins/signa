import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'
import { TOKEN_KEY } from '@/lib/constants'

const PUBLIC_PATHS = ['/login', '/api', '/favicon.ico']

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl

  // Allow public paths
  if (PUBLIC_PATHS.some((p) => pathname.startsWith(p))) {
    return NextResponse.next()
  }

  // Check for auth token in cookie
  const token = request.cookies.get(TOKEN_KEY)?.value

  if (!token) {
    const loginUrl = new URL('/login', request.url)
    loginUrl.searchParams.set('redirect', pathname)
    return NextResponse.redirect(loginUrl)
  }

  return NextResponse.next()
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
}
