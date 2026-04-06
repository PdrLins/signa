'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { useToast } from '@/hooks/useToast'
import { useBrainHighlights, useBrainChallenge, useBrainVerify } from '@/hooks/useBrain'
import { DEFAULT_TIMEZONE } from '@/lib/utils'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { Skeleton } from '@/components/ui/Skeleton'
import { Lock, Brain } from 'lucide-react'
import { useI18nStore } from '@/store/i18nStore'

type Step = 'locked' | 'otp'

export function BrainLocked() {
  const theme = useTheme()
  const toast = useToast()
  const t = useI18nStore((s) => s.t)
  const { data: highlights, isLoading } = useBrainHighlights()
  const challenge = useBrainChallenge()
  const verify = useBrainVerify()

  const [step, setStep] = useState<Step>('locked')
  const [otpDigits, setOtpDigits] = useState<string[]>(['', '', '', '', '', ''])
  const [countdown, setCountdown] = useState(60)
  const inputRefs = useRef<(HTMLInputElement | null)[]>([])

  // Countdown timer for OTP
  useEffect(() => {
    if (step !== 'otp') return
    if (countdown <= 0) return
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
      toast.show((err as Error)?.message || t.brain.failedToSendCode, 'error')
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- t ref is stable
  }, [challenge, toast])

  const handleDigitChange = (idx: number, value: string) => {
    if (!/^\d?$/.test(value)) return
    const newDigits = [...otpDigits]
    newDigits[idx] = value
    setOtpDigits(newDigits)

    if (value && idx < 5) {
      inputRefs.current[idx + 1]?.focus()
    }

    // Auto-submit when all 6 entered
    if (value && idx === 5 && newDigits.every((d) => d)) {
      handleVerify(newDigits.join(''))
    }
  }

  const handleKeyDown = (idx: number, e: React.KeyboardEvent) => {
    if (e.key === 'Backspace' && !otpDigits[idx] && idx > 0) {
      inputRefs.current[idx - 1]?.focus()
    }
  }

  const handlePaste = (e: React.ClipboardEvent) => {
    const pasted = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6)
    if (pasted.length === 6) {
      const digits = pasted.split('')
      setOtpDigits(digits)
      handleVerify(pasted)
      e.preventDefault()
    }
  }

  const handleVerify = async (code: string) => {
    try {
      await verify.mutateAsync(code)
      toast.show(t.brain.editorUnlocked, 'success')
    } catch (err) {
      toast.show((err as Error)?.message || t.brain.invalidCode, 'error')
      setOtpDigits(['', '', '', '', '', ''])
      inputRefs.current[0]?.focus()
    }
  }

  const rulesByType = highlights?.rules_by_type ?? {}
  const totalRules = highlights?.active_rules ?? 0

  if (step === 'otp') {
    return (
      <div className="max-w-[400px] mx-auto mt-12">
        <Card>
          <div className="text-center space-y-4">
            <Brain size={32} style={{ color: theme.colors.primary, margin: '0 auto' }} />
            <h2 className="text-lg font-bold" style={{ color: theme.colors.text }}>{t.brain.telegramVerification}</h2>
            <p className="text-sm" style={{ color: theme.colors.textSub }}>
              {t.brain.otpSent}
            </p>

            {/* OTP inputs */}
            <div className="flex justify-center gap-2" onPaste={handlePaste}>
              {otpDigits.map((digit, i) => (
                <input
                  key={i}
                  ref={(el) => { inputRefs.current[i] = el }}
                  type="text"
                  inputMode="numeric"
                  maxLength={1}
                  value={digit}
                  aria-label={`OTP digit ${i + 1}`}
                  onChange={(e) => handleDigitChange(i, e.target.value)}
                  onKeyDown={(e) => handleKeyDown(i, e)}
                  className="w-10 sm:w-11 h-12 text-center text-lg font-bold rounded-xl outline-none transition-all"
                  style={{
                    backgroundColor: theme.colors.surfaceAlt,
                    border: `2px solid ${digit ? theme.colors.primary : theme.colors.border}`,
                    color: theme.colors.text,
                  }}
                  disabled={verify.isPending}
                />
              ))}
            </div>

            {/* Countdown */}
            <p
              className="text-sm font-semibold tabular-nums"
              style={{ color: countdown <= 10 ? theme.colors.down : theme.colors.textSub }}
            >
              {countdown > 0 ? `0:${countdown.toString().padStart(2, '0')} ${t.brain.remaining}` : t.brain.codeExpired}
            </p>

            <div className="flex gap-2 pt-2">
              <Button variant="secondary" onClick={() => setStep('locked')} fullWidth>
                {t.brain.cancel}
              </Button>
              <Button
                onClick={() => handleVerify(otpDigits.join(''))}
                disabled={otpDigits.some((d) => !d) || verify.isPending || countdown <= 0}
                fullWidth
              >
                {verify.isPending ? t.brain.verifying : t.brain.verifyCode}
              </Button>
            </div>
          </div>
        </Card>
      </div>
    )
  }

  return (
    <div className="max-w-[600px] mx-auto mt-8 space-y-4">
      <div className="text-center mb-6">
        <Brain size={36} style={{ color: theme.colors.primary, margin: '0 auto 8px' }} />
        <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>{t.brain.signalBrain}</h1>
        {Boolean(highlights?.last_rule_updated) && (
          <p className="text-xs mt-1" style={{ color: theme.colors.textSub }}>
            {new Date(String(highlights?.last_rule_updated)).toLocaleDateString('en-US', { timeZone: DEFAULT_TIMEZONE })}
          </p>
        )}
      </div>

      {/* Highlights — safe summary only, no architecture details */}
      <Card>
        <p className="text-[11px] font-semibold uppercase tracking-wide mb-3" style={{ color: theme.colors.textSub }}>
          {t.brain.highlights}
        </p>
        {isLoading ? (
          <Skeleton width="100%" height={100} />
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              {[
                { label: t.brain.activeRules, value: highlights?.active_rules },
                { label: t.brain.blockers, value: highlights?.blocker_count },
                { label: t.brain.safeIncomeRules, value: highlights?.safe_income_rules },
                { label: t.brain.highRiskRules, value: highlights?.high_risk_rules },
                { label: t.brain.knowledgeEntries, value: highlights?.total_knowledge },
              ].map((item) => (
                <div key={item.label}>
                  <p className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>{item.label}</p>
                  <p className="text-lg font-bold" style={{ color: theme.colors.text }}>{String(item.value ?? 0)}</p>
                </div>
              ))}
            </div>

            {/* Rule type breakdown */}
            {totalRules > 0 && (
              <div className="space-y-1.5 mt-2">
                <p className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>
                  {t.brain.rulesByType}
                </p>
                {Object.entries(rulesByType).map(([type, count]) => (
                  <div key={type} className="flex items-center gap-2">
                    <span className="text-[11px] w-24" style={{ color: theme.colors.textSub }}>{type}</span>
                    <div className="flex-1">
                      <ProgressBar value={(count / totalRules) * 100} color={theme.colors.primary} height={3} />
                    </div>
                    <span className="text-[11px] font-semibold w-6 text-right" style={{ color: theme.colors.text }}>
                      {count}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </Card>

      {/* Unlock button */}
      <Card>
        <div className="text-center space-y-3">
          <Lock size={20} style={{ color: theme.colors.textHint, margin: '0 auto' }} />
          <Button onClick={handleUnlock} disabled={challenge.isPending} fullWidth>
            {challenge.isPending ? t.brain.sendingCode : t.brain.unlockEditor}
          </Button>
          <p className="text-[10px]" style={{ color: theme.colors.textHint }}>
            {t.brain.requiresTelegram}
          </p>
        </div>
      </Card>
    </div>
  )
}
