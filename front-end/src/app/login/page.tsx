'use client'

import { useState, useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useThemeStore } from '@/store/themeStore'
import { useAuthStore } from '@/store/authStore'
import { authApi } from '@/lib/api'
import { Eye, EyeOff, Activity, Cpu, Send, ArrowLeft, Shield } from 'lucide-react'

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
      setSessionToken(res.session_token)
      if (res.last_login) {
        localStorage.setItem('signa-last-login', res.last_login)
      }
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
      router.push('/overview')
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
      setSessionToken(res.session_token)
    } catch {
      setError(t.login.resendFailed)
    }
  }

  const features = [
    { icon: Activity, label: t.login.featureScanning, desc: t.login.featureScanningDesc },
    { icon: Cpu, label: t.login.featureAi, desc: t.login.featureAiDesc },
    { icon: Send, label: t.login.featureAlerts, desc: t.login.featureAlertsDesc },
  ]

  return (
    <div
      className="min-h-screen flex"
      style={{ backgroundColor: theme.colors.bg }}
    >
      {/* Left: branding panel — dark */}
      <div
        className="hidden lg:flex flex-col justify-between w-[520px] p-14 relative overflow-hidden"
        style={{
          background: 'linear-gradient(165deg, #0a0a0a 0%, #141414 50%, #1a1a1a 100%)',
        }}
      >
        {/* Subtle accent glow */}
        <div
          className="absolute -top-40 -right-40 w-96 h-96 rounded-full opacity-[0.07]"
          style={{ backgroundColor: theme.colors.primary }}
        />
        <div
          className="absolute -bottom-32 -left-32 w-72 h-72 rounded-full opacity-[0.05]"
          style={{ backgroundColor: theme.colors.primary }}
        />

        <div className="relative z-10">
          <h1 className="text-[42px] font-bold text-white tracking-tight leading-none">
            Signa
          </h1>
          <p className="text-white/80 mt-4 text-xl font-medium leading-snug">
            {t.login.subtitle}
          </p>
          <p className="text-white/50 mt-3 text-sm leading-relaxed max-w-[380px]">
            {t.login.tagline}
          </p>
        </div>

        <div className="relative z-10 space-y-5">
          {features.map((feat) => (
            <div key={feat.label} className="flex items-start gap-4">
              <div
                className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
                style={{ backgroundColor: 'rgba(255,255,255,0.06)' }}
              >
                <feat.icon size={18} className="text-white/90" />
              </div>
              <div>
                <p className="text-white/90 text-sm font-semibold">{feat.label}</p>
                <p className="text-white/50 text-[13px] mt-0.5">{feat.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Right: form panel */}
      <div className="flex-1 flex items-center justify-center px-6">
        <div className="w-full max-w-[380px]">
          {/* Mobile header */}
          <div className="lg:hidden mb-8">
            <div
              className="rounded-2xl px-6 py-8 mb-6 relative overflow-hidden"
              style={{
                background: 'linear-gradient(165deg, #0a0a0a 0%, #141414 50%, #1a1a1a 100%)',
              }}
            >
              <div
                className="absolute -top-20 -right-20 w-48 h-48 rounded-full opacity-[0.07]"
                style={{ backgroundColor: theme.colors.primary }}
              />
              <h1 className="text-[28px] font-bold text-white tracking-tight leading-none relative z-10">
                Signa
              </h1>
              <p className="text-white/70 mt-2 text-sm font-medium relative z-10">
                {t.login.subtitle}
              </p>
            </div>
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
                    className="w-full rounded-xl px-4 py-3 text-sm outline-none transition-all"
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
                      className="flex-1 bg-transparent outline-none text-sm"
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
                    style={{ backgroundColor: theme.colors.primary, color: theme.colors.surface }}
                  >
                    {loading ? t.login.signingIn : t.login.continue}
                  </button>
                </div>
              </form>
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
                      className="w-12 h-14 text-center text-lg font-bold rounded-xl outline-none transition-all duration-200"
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
