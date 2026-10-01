'use client'

import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import Link from 'next/link'
import { MoreHorizontal, type LucideIcon } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'

export interface ActionMenuItem {
  key: string
  label: string
  icon?: LucideIcon
  /** a link item (navigates) … */
  href?: string
  /** … or an action item */
  onSelect?: () => void
  danger?: boolean
  disabled?: boolean
}

/** One "⋯" (or custom) button that opens a small menu of actions. Replaces
 *  rows of buttons: a row or card keeps one tap target (open the page) and
 *  everything else lives here. Escape / outside click close it; arrow keys
 *  move between items; focus returns to the button. */
export function ActionMenu({ items, label, trigger, align = 'right', variant = 'icon' }: {
  items: ActionMenuItem[]
  /** aria-label of the button (and its tooltip) */
  label: string
  /** custom button content (icon + text); default is a "⋯" icon */
  trigger?: ReactNode
  align?: 'left' | 'right'
  /** icon: round ghost button · primary: filled accent button */
  variant?: 'icon' | 'primary'
}) {
  const theme = useTheme()
  const c = theme.colors
  const [open, setOpen] = useState(false)
  // Fixed position from the button's rect, so a menu inside a scrolling
  // table or a clipped card is never cut off. Opens upward near the bottom.
  const [pos, setPos] = useState<React.CSSProperties>({})
  const menuId = useId()
  const wrapRef = useRef<HTMLDivElement>(null)
  const btnRef = useRef<HTMLButtonElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  const close = useCallback((refocus = true) => {
    setOpen(false)
    if (refocus) btnRef.current?.focus()
  }, [])

  const toggle = () => {
    if (open) { setOpen(false); return }
    const r = btnRef.current?.getBoundingClientRect()
    if (r) {
      const up = window.innerHeight - r.bottom < 280 && r.top > 280
      const horiz = align === 'right' ? { right: Math.max(8, window.innerWidth - r.right) } : { left: Math.max(8, r.left) }
      setPos(up ? { ...horiz, bottom: window.innerHeight - r.top + 4 } : { ...horiz, top: r.bottom + 4 })
    }
    setOpen(true)
  }

  useEffect(() => {
    if (!open) return
    listRef.current?.querySelector<HTMLElement>('[role="menuitem"]:not([aria-disabled="true"])')?.focus()
    const onDown = (e: MouseEvent | TouchEvent) => {
      const target = e.target as Node
      if (wrapRef.current?.contains(target) || listRef.current?.contains(target)) return
      close(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); close() }
      if (e.key === 'Tab') close(false)
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault()
        const els = Array.from(listRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not([aria-disabled="true"])') ?? [])
        if (!els.length) return
        const i = els.indexOf(document.activeElement as HTMLElement)
        const next = e.key === 'ArrowDown' ? (i + 1) % els.length : (i - 1 + els.length) % els.length
        els[next].focus()
      }
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('touchstart', onDown)
    document.addEventListener('keydown', onKey)
    const onScroll = (e: Event) => { if (!listRef.current?.contains(e.target as Node)) close(false) }
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onScroll)
    return () => {
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', onScroll)
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('touchstart', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, close])

  const shown = items.filter(Boolean)
  if (!shown.length) return null

  const itemCls = 'w-full min-h-[44px] px-3 rounded-lg text-left text-[14px] flex items-center gap-2.5 focus-visible:outline focus-visible:outline-2 hover:brightness-125'
  const btnStyle = variant === 'primary'
    ? { backgroundColor: c.primary, color: c.surface, outlineColor: c.primary }
    : { backgroundColor: 'transparent', color: c.textSub, outlineColor: c.primary }

  return (
    <div className="relative shrink-0" ref={wrapRef}>
      <button ref={btnRef} type="button" onClick={toggle}
        aria-haspopup="menu" aria-expanded={open} aria-controls={open ? menuId : undefined}
        aria-label={label} title={label}
        className={`min-h-[44px] min-w-[44px] rounded-full inline-flex items-center justify-center gap-2 focus-visible:outline focus-visible:outline-2 ${variant === 'primary' ? 'px-4 text-[14px] font-semibold rounded-xl' : 'hover:brightness-125'}`}
        style={btnStyle}>
        {trigger ?? <MoreHorizontal size={18} aria-hidden="true" />}
      </button>
      {/* Portal to <body>: a CSS filter or transform on a parent (the rows'
          hover brightness) would otherwise anchor this fixed menu to that
          parent instead of the viewport. */}
      {open && typeof document !== 'undefined' && createPortal(
        <div ref={listRef} id={menuId} role="menu" aria-label={label}
          className="fixed z-[75] min-w-[220px] max-w-[min(320px,90vw)] rounded-xl p-1 flex flex-col shadow-xl"
          style={{ ...pos, backgroundColor: c.surfaceAlt, border: `1px solid ${c.border}` }}>
          {shown.map((it) => {
            const color = it.danger ? c.down : c.text
            const content = (
              <>
                {it.icon && <it.icon size={16} aria-hidden="true" style={{ color: it.danger ? c.down : c.textSub }} />}
                <span className="min-w-0 truncate">{it.label}</span>
              </>
            )
            if (it.href && !it.disabled) {
              return (
                <Link key={it.key} href={it.href} role="menuitem" tabIndex={-1} onClick={() => close(false)}
                  className={itemCls} style={{ color, outlineColor: c.primary }}>
                  {content}
                </Link>
              )
            }
            return (
              <button key={it.key} type="button" role="menuitem" tabIndex={-1} aria-disabled={it.disabled || undefined}
                disabled={it.disabled}
                onClick={() => { close(false); it.onSelect?.() }}
                className={`${itemCls} disabled:opacity-50`} style={{ color, outlineColor: c.primary }}>
                {content}
              </button>
            )
          })}
        </div>,
        document.body,
      )}
    </div>
  )
}
