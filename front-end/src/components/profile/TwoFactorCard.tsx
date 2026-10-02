'use client'

import { useEffect, useId, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, MessageSquare, Send, ShieldCheck } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useToast } from '@/hooks/useToast'
import { authApi, type TwoFactorSetup, type TwoFactorStatus } from '@/lib/api'
import { fill } from '@/lib/insights'
import { isMigrationRequired } from '@/lib/trackerErrors'
import { toHoldingsError } from '@/hooks/useHoldings'
import { LoadError, SectionCard, SoonBadge, useButtonStyles, useFieldStyle } from '@/components/profile/ui'

const KEY = ['auth', '2fa'] as const

/** Profile → Two-step sign-in (GET /auth/2fa, migration 020). Telegram now,
 *  SMS shown as coming soon. Setup: open the Signa bot from a one-time link,
 *  press Start, type the 6-digit code it sends. Hidden before migration 020. */
export function TwoFactorCard() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tf = t.profile.twoFactor
  const toast = useToast()
  const qc = useQueryClient()
  const btn = useButtonStyles()
  const f = useFieldStyle()
  const ids = { code: useId(), pw: useId() }
  const [setup, setSetup] = useState<TwoFactorSetup | null>(null)
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [disabling, setDisabling] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const q = useQuery<TwoFactorStatus, unknown>({
    queryKey: KEY,
    queryFn: () => authApi.twoFactor(),
    retry: false,
    // while waiting for "Start" in Telegram, poll until the bot sends the code
    refetchInterval: (query) => (query.state.data?.setup?.step === 'open_telegram' || setup?.step === 'open_telegram' ? 3000 : false),
  })
  const data = q.data
  // the server's view wins (the link url only exists in our local copy)
  const current: TwoFactorSetup | null = data?.setup
    ? { ...data.setup, url: data.setup.url ?? (setup?.step === 'open_telegram' ? setup.url : null) }
    : null

  useEffect(() => { if (data?.enabled) setSetup(null) }, [data?.enabled])

  if (isMigrationRequired(q.error)) return null

  const errText = (e: unknown) => {
    const he = toHoldingsError(e)
    const map = tf.errors as Record<string, string>
    const left = Number((he.extra as Record<string, unknown> | undefined)?.attempts_remaining)
    if (he.code === 'invalid_code' && Number.isFinite(left)) return fill(tf.errors.invalid_code_left, { n: left })
    return map[he.code] ?? tf.errors.generic
  }

  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try { await fn() } catch (e) { setError(errText(e)) } finally { setBusy(false) }
  }

  const start = (useConnected: boolean) => run(async () => {
    const s = await authApi.twoFactorStart(useConnected)
    setSetup(s)
    setCode('')
    await qc.invalidateQueries({ queryKey: KEY })
  })
  const resend = () => run(async () => {
    setSetup(await authApi.twoFactorResend())
    toast.show(tf.resent, 'info', 2000)
  })
  const confirm = () => run(async () => {
    await authApi.twoFactorConfirm(code.trim())
    toast.show(tf.turnedOn, 'success', 2500)
    setSetup(null)
    setCode('')
    await qc.invalidateQueries({ queryKey: KEY })
  })
  const cancel = () => run(async () => {
    await authApi.twoFactorCancel()
    setSetup(null)
    await qc.invalidateQueries({ queryKey: KEY })
  })
  const disable = () => run(async () => {
    await authApi.twoFactorDisable(password)
    toast.show(tf.turnedOff, 'info', 2500)
    setPassword('')
    setDisabling(false)
    await qc.invalidateQueries({ queryKey: KEY })
  })

  const errorLine = error && <p role="alert" className="text-[13px]" style={{ color: theme.colors.down }}>{error}</p>

  return (
    <SectionCard title={tf.title} subtitle={tf.subtitle}>
      {q.isLoading && <div className="h-14 rounded-xl animate-pulse" style={{ backgroundColor: theme.colors.surfaceAlt }} />}
      {!!q.error && <LoadError message={tf.errors.generic} onRetry={() => q.refetch()} />}

      {data?.enabled && (
        <div className="flex flex-col gap-3">
          <p className="flex items-center gap-2 text-[14px] font-medium" style={{ color: theme.colors.up }}>
            <ShieldCheck size={18} aria-hidden="true" />{tf.on}
          </p>
          {!data.can_disable ? (
            <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{tf.ownerRequired}</p>
          ) : !disabling ? (
            <button type="button" onClick={() => { setDisabling(true); setError(null) }}
              className={`${btn.secondary.className} self-start`} style={btn.secondary.style}>{tf.turnOff}</button>
          ) : (
            <form className="flex flex-col gap-2" onSubmit={(e) => { e.preventDefault(); if (password) disable() }}>
              <label htmlFor={ids.pw} className={f.label} style={{ color: f.labelColor }}>
                {tf.passwordToTurnOff}
                <input id={ids.pw} type="password" autoComplete="current-password" value={password}
                  onChange={(e) => setPassword(e.target.value)} className={`${f.input} sm:max-w-[320px]`} style={f.style} />
              </label>
              {errorLine}
              <div className="flex flex-wrap gap-2">
                <button type="submit" disabled={busy || !password} className={btn.danger.className} style={btn.danger.style}>{tf.turnOff}</button>
                <button type="button" onClick={() => { setDisabling(false); setPassword(''); setError(null) }}
                  className={btn.secondary.className} style={btn.secondary.style}>{t.tracker.cancel}</button>
              </div>
            </form>
          )}
        </div>
      )}

      {data && !data.enabled && !current && (
        <div className="flex flex-col gap-3">
          <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{tf.offExplain}</p>
          <ul className="flex flex-col gap-2">
            <li className="flex flex-wrap items-center gap-3 rounded-xl px-3 py-3" style={{ backgroundColor: theme.colors.surfaceAlt }}>
              <Send size={18} aria-hidden="true" style={{ color: theme.colors.primary }} />
              <span className="flex-1 min-w-[160px]">
                <span className="block text-[14px] font-medium" style={{ color: theme.colors.text }}>Telegram</span>
                <span className="block text-[12px]" style={{ color: theme.colors.textSub }}>
                  {data.telegram.available ? tf.telegramDesc : tf.telegramUnavailable}
                </span>
              </span>
              {data.telegram.available && (
                <span className="flex flex-wrap gap-2">
                  {data.telegram.connected_chat && (
                    <button type="button" onClick={() => start(true)} disabled={busy}
                      className={btn.secondary.className} style={btn.secondary.style}>
                      {fill(tf.useConnected, { chat: data.telegram.connected_chat })}
                    </button>
                  )}
                  <button type="button" onClick={() => start(false)} disabled={busy}
                    className={btn.primary.className} style={btn.primary.style}>{tf.setUp}</button>
                </span>
              )}
            </li>
            <li className="flex items-center gap-3 rounded-xl px-3 py-3 opacity-70" style={{ backgroundColor: theme.colors.surfaceAlt }}>
              <MessageSquare size={18} aria-hidden="true" style={{ color: theme.colors.textSub }} />
              <span className="flex-1">
                <span className="block text-[14px] font-medium" style={{ color: theme.colors.text }}>{tf.sms}</span>
                <span className="block text-[12px]" style={{ color: theme.colors.textSub }}>{tf.smsDesc}</span>
              </span>
              <SoonBadge label={t.tracker.comingSoon} />
            </li>
          </ul>
          {errorLine}
        </div>
      )}

      {data && !data.enabled && current?.step === 'open_telegram' && (
        <div className="flex flex-col gap-3">
          <ol className="flex flex-col gap-2.5">
            {[tf.steps.install, tf.steps.open, tf.steps.start, tf.steps.code].map((s, i) => (
              <li key={i} className="flex gap-3 text-[14px]" style={{ color: theme.colors.text }}>
                <span className="w-6 h-6 rounded-full shrink-0 inline-flex items-center justify-center text-[12px] font-bold"
                  style={{ backgroundColor: theme.colors.primary + '26', color: theme.colors.primary }}>{i + 1}</span>
                <span className="pt-0.5">{fill(s, { bot: data.telegram.bot_username ? `@${data.telegram.bot_username}` : 'Signa' })}</span>
              </li>
            ))}
          </ol>
          <div className="flex flex-wrap gap-2">
            {current.url ? (
              <a href={current.url} target="_blank" rel="noopener noreferrer" className={btn.primary.className} style={btn.primary.style}>
                <ExternalLink size={16} aria-hidden="true" />{tf.openTelegram}
              </a>
            ) : (
              <button type="button" onClick={() => start(false)} disabled={busy} className={btn.primary.className} style={btn.primary.style}>
                {tf.newLink}
              </button>
            )}
            <button type="button" onClick={cancel} disabled={busy} className={btn.secondary.className} style={btn.secondary.style}>{t.tracker.cancel}</button>
          </div>
          <p role="status" aria-live="polite" className="text-[12px]" style={{ color: theme.colors.textHint }}>{tf.waiting}</p>
          {errorLine}
        </div>
      )}

      {data && !data.enabled && current?.step === 'enter_code' && (
        <form className="flex flex-col gap-2" onSubmit={(e) => { e.preventDefault(); if (/^\d{6}$/.test(code.trim())) confirm() }}>
          <p className="text-[14px]" style={{ color: theme.colors.text }}>
            {fill(tf.codeSent, { chat: current.chat_label ?? 'Telegram' })}
          </p>
          <label htmlFor={ids.code} className={f.label} style={{ color: f.labelColor }}>
            {tf.codeLabel}
            <input id={ids.code} inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
              className={`${f.input} sm:max-w-[200px] tracking-[0.3em] font-mono`} style={f.style} />
          </label>
          {errorLine}
          <div className="flex flex-wrap gap-2">
            <button type="submit" disabled={busy || code.trim().length !== 6} className={btn.primary.className} style={btn.primary.style}>{tf.turnOn}</button>
            <button type="button" onClick={resend} disabled={busy} className={btn.secondary.className} style={btn.secondary.style}>{tf.resend}</button>
            <button type="button" onClick={cancel} disabled={busy} className={btn.secondary.className} style={btn.secondary.style}>{t.tracker.cancel}</button>
          </div>
        </form>
      )}
    </SectionCard>
  )
}
