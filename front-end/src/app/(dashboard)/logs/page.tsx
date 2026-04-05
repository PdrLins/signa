'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { useToast } from '@/hooks/useToast'
import { useI18nStore } from '@/store/i18nStore'
import { useBrainStore } from '@/store/brainStore'
import { useBrainChallenge, useBrainVerify } from '@/hooks/useBrain'
import { client } from '@/lib/api'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Brain, Lock, Search, Pause, Play, ArrowDown } from 'lucide-react'

interface LogEntry {
  timestamp: string
  level: string
  module: string
  function: string
  line: number
  message: string
}

const LEVEL_COLORS: Record<string, string> = {
  DEBUG: '#6B7280',
  INFO: '#3B82F6',
  WARNING: '#F59E0B',
  ERROR: '#EF4444',
  CRITICAL: '#DC2626',
  SUCCESS: '#10B981',
}

function LogLine({ entry }: { entry: LogEntry }) {
  const theme = useTheme()
  const levelColor = LEVEL_COLORS[entry.level] || theme.colors.textSub
  const time = new Date(entry.timestamp).toLocaleTimeString('en-US', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  })

  return (
    <div className="flex gap-2 py-0.5 px-3 hover:bg-white/5 font-mono text-[12px] leading-relaxed">
      <span className="text-[11px] shrink-0 tabular-nums" style={{ color: theme.colors.textHint }}>{time}</span>
      <span
        className="text-[10px] font-bold w-[52px] shrink-0 text-right"
        style={{ color: levelColor }}
      >
        {entry.level}
      </span>
      <span className="text-[11px] shrink-0 w-[100px] truncate" style={{ color: theme.colors.textSub }}>
        {entry.module}
      </span>
      <span className="flex-1 break-all" style={{ color: theme.colors.text }}>
        {entry.message}
      </span>
    </div>
  )
}

function LogViewer() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const brainToken = useBrainStore((s) => s.brainToken)
  const lock = useBrainStore((s) => s.lock)
  const remaining = useBrainStore((s) => s.getRemainingSeconds)

  const [logs, setLogs] = useState<LogEntry[]>([])
  const [filter, setFilter] = useState('')
  const [levelFilter, setLevelFilter] = useState<string>('ALL')
  const [paused, setPaused] = useState(false)
  const [autoScroll, setAutoScroll] = useState(true)
  const [connected, setConnected] = useState(false)
  const [secs, setSecs] = useState(remaining())

  const scrollRef = useRef<HTMLDivElement>(null)
  const wsRef = useRef<WebSocket | null>(null)

  // Timer
  useEffect(() => {
    const t = setInterval(() => setSecs(remaining()), 1000)
    return () => clearInterval(t)
  }, [remaining])

  // Load initial logs
  useEffect(() => {
    if (!brainToken) return
    client.get('/logs/recent', {
      params: { limit: 200 },
      headers: { 'X-Brain-Token': brainToken },
    }).then((res) => {
      setLogs((res.data as { logs: LogEntry[] }).logs)
    }).catch(() => {})
  }, [brainToken])

  // WebSocket connection
  useEffect(() => {
    if (!brainToken) return

    const wsUrl = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1')
      .replace('http', 'ws')
    const ws = new WebSocket(`${wsUrl}/logs/stream?token=${brainToken}`)
    wsRef.current = ws

    ws.onopen = () => setConnected(true)
    ws.onclose = () => setConnected(false)
    ws.onerror = () => setConnected(false)
    ws.onmessage = (event) => {
      if (paused) return
      try {
        const entry = JSON.parse(event.data) as LogEntry
        setLogs((prev) => [...prev.slice(-499), entry])
      } catch {}
    }

    return () => {
      ws.close()
      wsRef.current = null
    }
  }, [brainToken, paused])

  // Auto-scroll
  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [logs, autoScroll])

  const filteredLogs = logs.filter((l) => {
    if (levelFilter !== 'ALL' && l.level !== levelFilter) return false
    if (filter && !l.message.toLowerCase().includes(filter.toLowerCase()) && !l.module.toLowerCase().includes(filter.toLowerCase())) return false
    return true
  })

  const levels = ['ALL', 'DEBUG', 'INFO', 'WARNING', 'ERROR']
  const mins = Math.floor(secs / 60)
  const s = secs % 60
  const timerColor = secs > 180 ? theme.colors.up : secs > 60 ? theme.colors.warning : theme.colors.down

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-bold" style={{ color: theme.colors.text }}>{t.logs.systemLogs}</h1>
          <div className="flex items-center gap-1.5">
            <span
              className="w-2 h-2 rounded-full"
              style={{ backgroundColor: connected ? theme.colors.up : theme.colors.down, animation: connected ? 'pulse 2s infinite' : 'none' }}
            />
            <span className="text-[10px]" style={{ color: connected ? theme.colors.up : theme.colors.down }}>
              {connected ? t.logs.live : t.logs.disconnected}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs tabular-nums" style={{ color: timerColor }}>
            {mins}:{s.toString().padStart(2, '0')}
          </span>
          <Button variant="secondary" onClick={lock}>
            <span className="flex items-center gap-1"><Lock size={12} /> {t.logs.lock}</span>
          </Button>
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-2 flex-wrap">
        {/* Search */}
        <div
          className="flex items-center gap-2 flex-1 min-w-[200px] rounded-lg px-3 py-1.5"
          style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}` }}
        >
          <Search size={14} style={{ color: theme.colors.textHint }} />
          <input
            placeholder={t.logs.filterLogs}
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="flex-1 bg-transparent text-sm outline-none"
            style={{ color: theme.colors.text }}
          />
        </div>

        {/* Level filter */}
        <div className="flex items-center gap-0.5 rounded-lg px-0.5 py-0.5" style={{ backgroundColor: theme.colors.nav }}>
          {levels.map((lvl) => (
            <button
              key={lvl}
              onClick={() => setLevelFilter(lvl)}
              className="px-2 py-1 rounded-md text-[10px] font-medium transition-all"
              style={{
                backgroundColor: levelFilter === lvl ? theme.colors.navActive : 'transparent',
                color: levelFilter === lvl ? theme.colors.text : LEVEL_COLORS[lvl] || theme.colors.textSub,
              }}
            >
              {lvl}
            </button>
          ))}
        </div>

        {/* Controls */}
        <button
          onClick={() => setPaused(!paused)}
          className="p-1.5 rounded-lg transition-all"
          style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.textSub }}
          title={paused ? 'Resume' : 'Pause'}
        >
          {paused ? <Play size={14} /> : <Pause size={14} />}
        </button>
        <button
          onClick={() => setAutoScroll(!autoScroll)}
          className="p-1.5 rounded-lg transition-all"
          style={{
            backgroundColor: autoScroll ? theme.colors.primary + '15' : theme.colors.surfaceAlt,
            color: autoScroll ? theme.colors.primary : theme.colors.textSub,
          }}
          title={autoScroll ? 'Auto-scroll on' : 'Auto-scroll off'}
        >
          <ArrowDown size={14} />
        </button>
      </div>

      {/* Log output */}
      <div
        ref={scrollRef}
        className="rounded-xl overflow-hidden overflow-y-auto"
        style={{
          backgroundColor: theme.isDark ? '#0D1117' : '#1E1E2E',
          border: `1px solid ${theme.colors.border}`,
          height: 'calc(100vh - 260px)',
          minHeight: 400,
        }}
      >
        <div className="py-2">
          {filteredLogs.length === 0 ? (
            <p className="text-center py-12 text-sm" style={{ color: '#6B7280' }}>
              {logs.length === 0 ? t.logs.waitingForLogs : t.logs.noMatch}
            </p>
          ) : (
            filteredLogs.map((entry, i) => <LogLine key={i} entry={entry} />)
          )}
        </div>
      </div>

      {/* Status bar */}
      <div className="flex items-center justify-between">
        <span className="text-[10px]" style={{ color: theme.colors.textHint }}>
          {filteredLogs.length} / {logs.length} {t.logs.entries}
          {paused && ` (${t.logs.paused})`}
        </span>
        <span className="text-[10px]" style={{ color: theme.colors.textHint }}>
          {t.logs.buffer}: {logs.length}/500
        </span>
      </div>
    </div>
  )
}

// OTP unlock flow (reuses brain 2FA)
function LogsLocked() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const toast = useToast()
  const challenge = useBrainChallenge()
  const verify = useBrainVerify()
  const [step, setStep] = useState<'locked' | 'otp'>('locked')
  const [otpDigits, setOtpDigits] = useState(['', '', '', '', '', ''])
  const [countdown, setCountdown] = useState(60)
  const inputRefs = useRef<(HTMLInputElement | null)[]>([])

  useEffect(() => {
    if (step !== 'otp' || countdown <= 0) return
    const t = setInterval(() => setCountdown((c) => c - 1), 1000)
    return () => clearInterval(t)
  }, [step, countdown])

  const handleUnlock = useCallback(async () => {
    try {
      await challenge.mutateAsync()
      setStep('otp')
      setCountdown(60)
      setOtpDigits(['', '', '', '', '', ''])
      setTimeout(() => inputRefs.current[0]?.focus(), 100)
    } catch (err) {
      toast.show((err as Error)?.message || 'Failed', 'error')
    }
  }, [challenge, toast])

  const handleDigitChange = (idx: number, value: string) => {
    if (!/^\d?$/.test(value)) return
    const d = [...otpDigits]
    d[idx] = value
    setOtpDigits(d)
    if (value && idx < 5) inputRefs.current[idx + 1]?.focus()
    if (value && idx === 5 && d.every((x) => x)) handleVerify(d.join(''))
  }

  const handleKeyDown = (idx: number, e: React.KeyboardEvent) => {
    if (e.key === 'Backspace' && !otpDigits[idx] && idx > 0) inputRefs.current[idx - 1]?.focus()
  }

  const handlePaste = (e: React.ClipboardEvent) => {
    const p = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6)
    if (p.length === 6) { setOtpDigits(p.split('')); handleVerify(p); e.preventDefault() }
  }

  const handleVerify = async (code: string) => {
    try {
      await verify.mutateAsync(code)
      toast.show('Logs unlocked', 'success')
    } catch (err) {
      toast.show((err as Error)?.message || 'Invalid code', 'error')
      setOtpDigits(['', '', '', '', '', ''])
      inputRefs.current[0]?.focus()
    }
  }

  if (step === 'otp') {
    return (
      <div className="max-w-[400px] mx-auto mt-12">
        <Card>
          <div className="text-center space-y-4">
            <Brain size={32} style={{ color: theme.colors.primary, margin: '0 auto' }} />
            <h2 className="text-lg font-bold" style={{ color: theme.colors.text }}>{t.logs.telegramVerification}</h2>
            <p className="text-sm" style={{ color: theme.colors.textSub }}>
              {t.logs.otpSent}
            </p>
            <div className="flex justify-center gap-2" onPaste={handlePaste}>
              {otpDigits.map((d, i) => (
                <input
                  key={i}
                  ref={(el) => { inputRefs.current[i] = el }}
                  type="text" inputMode="numeric" maxLength={1} value={d}
                  onChange={(e) => handleDigitChange(i, e.target.value)}
                  onKeyDown={(e) => handleKeyDown(i, e)}
                  className="w-10 sm:w-11 h-12 text-center text-lg font-bold rounded-xl outline-none"
                  style={{ backgroundColor: theme.colors.surfaceAlt, border: `2px solid ${d ? theme.colors.primary : theme.colors.border}`, color: theme.colors.text }}
                />
              ))}
            </div>
            <p className="text-sm tabular-nums" style={{ color: countdown <= 10 ? theme.colors.down : theme.colors.textSub }}>
              {countdown > 0 ? `0:${countdown.toString().padStart(2, '0')} ${t.logs.remaining}` : t.brain.codeExpired}
            </p>
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setStep('locked')} fullWidth>{t.logs.cancel}</Button>
              <Button onClick={() => handleVerify(otpDigits.join(''))} disabled={otpDigits.some((x) => !x) || verify.isPending || countdown <= 0} fullWidth>
                {verify.isPending ? t.logs.verifying : t.logs.verify}
              </Button>
            </div>
          </div>
        </Card>
      </div>
    )
  }

  return (
    <div className="max-w-[400px] mx-auto mt-16 text-center space-y-4">
      <Brain size={36} style={{ color: theme.colors.primary, margin: '0 auto' }} />
      <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>{t.logs.systemLogs}</h1>
      <p className="text-sm" style={{ color: theme.colors.textSub }}>
        {t.logs.requiresElevated}
      </p>
      <Card>
        <div className="text-center space-y-3">
          <Lock size={20} style={{ color: theme.colors.textHint, margin: '0 auto' }} />
          <Button onClick={handleUnlock} disabled={challenge.isPending} fullWidth>
            {challenge.isPending ? t.brain.sendingCode : t.logs.unlockLogs}
          </Button>
          <p className="text-[10px]" style={{ color: theme.colors.textHint }}>
            {t.logs.requiresTelegram}
          </p>
        </div>
      </Card>
    </div>
  )
}

export default function LogsPage() {
  const isUnlocked = useBrainStore((s) => s.isUnlocked)
  return isUnlocked ? <LogViewer /> : <LogsLocked />
}
