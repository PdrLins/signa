'use client'

import { useState, useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useThemeStore } from '@/store/themeStore'
import { useAuthStore } from '@/store/authStore'
import { authApi } from '@/lib/api'
import { LangSwitcher } from '@/components/ui/LangSwitcher'
import { LoginShowcase } from '@/components/login/LoginShowcase'
import Link from 'next/link'
import { Eye, EyeOff, ArrowLeft, Shield } from 'lucide-react'

export default function LoginPage() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const router = useRouter()
  const initTheme = useThemeStore((s) => s.initialize)
  const setToken = useAuthStore((s) => s.setToken)

  const [step, setStep] = useState<1 | 2>(1)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [sessionToken, setSessionToken] = useState('')
  const [otp, setOtp] = useState(['', '', '', '', '', ''])
  const [countdown, setCountdown] = useState(120)
  const [attempts, setAttempts] = useState(0)
  const [error, setError] = useState(() => {
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search)
      const reason = params.get('reason')
      if (reason === 'expired') return t.login.sessionExpired ?? 'Your session has expired. Please log in again.'
    }
    return ''
  })
  const [loading, setLoading] = useState(false)

  const otpRefs = useRef<(HTMLInputElement | null)[]>([])

  useEffect(() => {
    initTheme()
  }, [initTheme])

  useEffect(() => {
    if (step !== 2 || countdown <= 0) return
    const timer = setInterval(() => setCountdown((c) => c - 1), 1000)
    return () => clearInterval(timer)
  }, [step, countdown])

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await authApi.login({ username, password })
      if (res.last_login) {
        localStorage.setItem('signa-last-login', res.last_login)
      }
      if (res.access_token) {
        // Password-only login — no Telegram code step
        setToken(res.access_token)
        router.push('/home')
        return
      }
      setSessionToken(res.session_token ?? '')
      setStep(2)
      setCountdown(30)
      setAttempts(0)
    } catch (err) {
      const msg = err instanceof Error ? err.message : ''
      if (msg.includes('locked') || msg.includes('Lock')) {
        setError(t.login.accountLocked)
      } else {
        setError(t.login.invalidCredentials)
      }
    } finally {
      setLoading(false)
    }
  }

  const handleOtpChange = (index: number, value: string) => {
    if (value.length > 1) value = value.slice(-1)
    if (!/^\d*$/.test(value)) return

    const newOtp = [...otp]
    newOtp[index] = value
    setOtp(newOtp)

    if (value && index < 5) {
      otpRefs.current[index + 1]?.focus()
    }
  }

  const handleOtpKeyDown = (index: number, e: React.KeyboardEvent) => {
    if (e.key === 'Backspace' && !otp[index] && index > 0) {
      otpRefs.current[index - 1]?.focus()
    }
  }

  const handleOtpPaste = (e: React.ClipboardEvent) => {
    const pasted = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6)
    if (pasted.length === 6) {
      setOtp(pasted.split(''))
      e.preventDefault()
    }
  }

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault()
    const code = otp.join('')
    if (code.length !== 6) return

    setError('')
    setLoading(true)
    try {
      const res = await authApi.verifyOtp({ session_token: sessionToken, otp_code: code })
      setToken(res.access_token)
      if (res.last_login) {
        localStorage.setItem('signa-last-login', res.last_login)
      }
      router.push('/home')
    } catch (err) {
      const msg = err instanceof Error ? err.message : ''
      const newAttempts = attempts + 1
      setAttempts(newAttempts)
      if (newAttempts >= 3) {
        setStep(1)
        setOtp(['', '', '', '', '', ''])
        setSessionToken('')
        setError(t.login.tooManyAttempts)
      } else if (msg.includes('expired') || msg.includes('Expired')) {
        setError(t.login.codeExpired ?? 'Code expired. Request a new one.')
        setOtp(['', '', '', '', '', ''])
      } else {
        setError(t.login.invalidCode.replace('{remaining}', String(3 - newAttempts)).replace('{s}', 3 - newAttempts > 1 ? 's' : ''))
        setOtp(['', '', '', '', '', ''])
        otpRefs.current[0]?.focus()
      }
    } finally {
      setLoading(false)
    }
  }

  const handleResend = async () => {
    setCountdown(30)
    setError('')
    try {
      const res = await authApi.login({ username, password })
      setSessionToken(res.session_token ?? '')
    } catch {
      setError(t.login.resendFailed)
    }
  }


  return (
    <div
      className="min-h-screen flex relative"
      style={{ backgroundColor: theme.colors.bg }}
    >
      <div className="absolute top-4 right-4 z-10">
        <LangSwitcher />
      </div>
      <LoginShowcase />

      {/* Right: form panel */}
      <div className="flex-1 flex items-center justify-center px-6">
        <div className="w-full max-w-[380px]">
          {/* Mobile header */}
          <div className="lg:hidden mb-8 flex flex-col gap-1.5">
            <p className="text-[26px] font-bold tracking-tight" style={{ color: theme.colors.text }}>Signa</p>
            <p className="text-[15px]" style={{ color: theme.colors.textSub }}>{t.login.subtitle}</p>
          </div>

          {step === 1 ? (
            <>
              <div className="hidden lg:block mb-8">
                <h2
                  className="text-2xl font-bold tracking-tight"
                  style={{ color: theme.colors.text }}
                >
                  {t.login.signIn}
                </h2>
                <p className="text-sm mt-1.5" style={{ color: theme.colors.textSub }}>
                  {t.login.signInDesc}
                </p>
              </div>

              <form onSubmit={handleLogin} className="space-y-5">
                <div>
                  <label
                    className="text-[13px] font-medium mb-2 block"
                    style={{ color: theme.colors.textSub }}
                  >
                    {t.login.username}
                  </label>
                  <input
                    type="text"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    className="w-full rounded-xl px-4 py-3 text-sm outline-0 transition-all"
                    style={{
                      backgroundColor: theme.colors.surfaceAlt,
                      color: theme.colors.text,
                      border: `1px solid ${theme.colors.border}`,
                    }}
                    autoFocus
                    aria-label={t.login.username}
                  />
                </div>

                <div>
                  <label
                    className="text-[13px] font-medium mb-2 block"
                    style={{ color: theme.colors.textSub }}
                  >
                    {t.login.password}
                  </label>
                  <div
                    className="flex items-center rounded-xl px-4 py-3 transition-all"
                    style={{
                      backgroundColor: theme.colors.surfaceAlt,
                      border: `1px solid ${theme.colors.border}`,
                    }}
                  >
                    <input
                      type={showPassword ? 'text' : 'password'}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      className="flex-1 bg-transparent outline-0 text-sm"
                      style={{ color: theme.colors.text }}
                      aria-label={t.login.password}
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      tabIndex={-1}
                      aria-label="Toggle password visibility"
                      className="ml-2 opacity-50 hover:opacity-80 transition-opacity"
                    >
                      {showPassword ? (
                        <EyeOff size={16} style={{ color: theme.colors.textSub }} />
                      ) : (
                        <Eye size={16} style={{ color: theme.colors.textSub }} />
                      )}
                    </button>
                  </div>
                </div>

                {error && (
                  <p className="text-[13px] font-medium" style={{ color: theme.colors.down }}>
                    {error}
                  </p>
                )}

                <div className="pt-1">
                  <button
                    type="submit"
                    disabled={!username.trim() || !password.trim() || loading}
                    className="w-full rounded-xl px-5 py-3.5 text-sm font-semibold transition-all hover:opacity-90 active:opacity-80 disabled:opacity-50 disabled:cursor-not-allowed"
                    // Day 32 fix: button text was using theme.colors.surface
                    // which is near-black on dark themes (Slate), giving
                    // unreadable dark-text-on-slate-blue. Use theme.isDark
                    // to pick the right contrast: white on dark themes, the
                    // existing surface (white) on light themes.
                    style={{
                      backgroundColor: theme.colors.primary,
                      color: theme.isDark ? theme.colors.text : theme.colors.surface,
                    }}
                  >
                    {loading ? t.login.signingIn : t.login.continue}
                  </button>
                </div>
              </form>
              <p className="mt-6 text-center text-sm">
                <Link
                  href="/pricing"
                  className="inline-flex min-h-[44px] items-center font-medium rounded-lg px-2 focus-visible:outline focus-visible:outline-2"
                  style={{ color: theme.colors.primary, outlineColor: theme.colors.primary }}
                >
                  {t.pricing.seePlans}
                </Link>
              </p>
            </>
          ) : (
            <>
              <button
                type="button"
                onClick={() => { setStep(1); setError(''); setOtp(['', '', '', '', '', '']) }}
                className="flex items-center gap-1.5 text-sm font-medium mb-8 transition-opacity hover:opacity-70"
                style={{ color: theme.colors.textSub }}
                aria-label={t.login.backToLogin}
              >
                <ArrowLeft size={14} />
                {t.login.backToLogin}
              </button>

              <div className="flex items-center gap-3 mb-2">
                <div
                  className="w-10 h-10 rounded-xl flex items-center justify-center"
                  style={{ backgroundColor: `${theme.colors.text}14` }}
                >
                  <Shield size={18} style={{ color: theme.colors.textSub }} />
                </div>
                <div>
                  <h2
                    className="text-xl font-bold leading-tight"
                    style={{ color: theme.colors.text }}
                  >
                    {t.login.checkTelegram}
                  </h2>
                </div>
              </div>
              <p className="text-sm mb-8 ml-[52px]" style={{ color: theme.colors.textSub }}>
                {t.login.otpSent}
              </p>

              <form onSubmit={handleVerify} className="space-y-6">
                <div className="flex justify-center gap-3" onPaste={handleOtpPaste}>
                  {otp.map((digit, i) => (
                    <input
                      key={i}
                      ref={(el) => { otpRefs.current[i] = el }}
                      type="text"
                      inputMode="numeric"
                      maxLength={1}
                      value={digit}
                      onChange={(e) => handleOtpChange(i, e.target.value)}
                      onKeyDown={(e) => handleOtpKeyDown(i, e)}
                      aria-label={`Digit ${i + 1}`}
                      className="w-12 h-14 text-center text-lg font-bold rounded-xl outline-0 transition-all duration-200"
                      style={{
                        backgroundColor: digit ? `${theme.colors.text}10` : theme.colors.surfaceAlt,
                        color: theme.colors.text,
                        border: `1.5px solid ${digit ? theme.colors.textSub : theme.colors.border}`,
                        boxShadow: digit ? `0 0 0 3px ${theme.colors.text}0D` : 'none',
                      }}
                    />
                  ))}
                </div>

                <div className="text-center">
                  <p
                    className="text-sm font-semibold tabular-nums"
                    style={{ color: countdown <= 10 ? theme.colors.down : theme.colors.textSub }}
                  >
                    {countdown > 0
                      ? t.login.remaining.replace('{seconds}', String(countdown))
                      : t.login.codeExpired}
                  </p>
                  <p className="text-xs mt-1" style={{ color: theme.colors.textHint }}>
                    {t.login.otpSecure}
                  </p>
                </div>

                {error && (
                  <p className="text-[13px] text-center font-medium" style={{ color: theme.colors.down }}>
                    {error}
                  </p>
                )}

                <button
                  type="submit"
                  disabled={otp.join('').length !== 6 || loading}
                  className="w-full rounded-xl px-5 py-3.5 text-sm font-semibold transition-all hover:opacity-90 active:opacity-80 disabled:opacity-50 disabled:cursor-not-allowed"
                  style={{ backgroundColor: theme.colors.primary, color: theme.colors.surface }}
                >
                  {loading ? t.login.verifying : t.login.verify}
                </button>

                <button
                  type="button"
                  onClick={handleResend}
                  disabled={countdown > 0}
                  className="w-full text-center text-sm font-medium transition-opacity"
                  style={{
                    color: countdown > 0 ? theme.colors.textHint : theme.colors.textSub,
                    opacity: countdown > 0 ? 0.4 : 1,
                    cursor: countdown > 0 ? 'not-allowed' : 'pointer',
                  }}
                  aria-label={t.login.resend}
                >
                  {t.login.resend}
                </button>
              </form>
            </>
          )}

        </div>
      </div>
    </div>
  )
}
