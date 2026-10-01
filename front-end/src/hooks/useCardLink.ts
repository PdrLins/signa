import { useCallback } from 'react'
import { useRouter } from 'next/navigation'

const INTERACTIVE = 'a,button,input,select,textarea,label,summary,[role="button"],[role="switch"],[role="radio"]'

/** Make a whole card / table row open `href` on click, while its own
 *  buttons, links and fields keep working and text selection isn't a click.
 *  Keep a real <Link> inside the card for keyboard and screen readers;
 *  this only widens the mouse/touch target. */
export function useCardLink(href: string | null | undefined) {
  const router = useRouter()
  const onClick = useCallback((e: React.MouseEvent) => {
    if (!href) return
    if ((e.target as HTMLElement).closest(INTERACTIVE)) return
    if (typeof window !== 'undefined' && window.getSelection()?.toString()) return
    if (e.metaKey || e.ctrlKey) {
      window.open(href, '_blank', 'noopener')
      return
    }
    router.push(href)
  }, [href, router])
  return href ? { onClick, className: 'cursor-pointer transition-colors' } : { onClick: undefined, className: '' }
}
