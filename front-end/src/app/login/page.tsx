'use client'

import { useState, useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useThemeStore } from '@/store/themeStore'
import { useAuthStore } from '@/store/authStore'
import { authApi } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import { User, Lock, Eye, EyeOff } from 'lucide-react'

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
  const [countdown, setCountdown] = useState(30)
  const [attempts, setAttempts] = useState(0)
  const [error, setError] = useState('')
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
      setStep(2)
      setCountdown(30)
      setAttempts(0)
    } catch (err) {
      setError(err instanceof Error ? err.message : t.login.invalidCredentials)
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
      router.push('/overview')
    } catch {
      const newAttempts = attempts + 1
      setAttempts(newAttempts)
      if (newAttempts >= 3) {
        setStep(1)
        setOtp(['', '', '', '', '', ''])
        setSessionToken('')
        setError(t.login.tooManyAttempts)
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

  return (
    <div
      className="min-h-screen flex items-center justify-center px-4"
      style={{ backgroundColor: theme.colors.bg }}
    >
      <div
        className="w-full max-w-[380px] rounded-2xl p-8"
        style={{
          backgroundColor: theme.colors.surface,
          border: `0.5px solid ${theme.colors.border}`,
          boxShadow: theme.isDark ? '0 4px 24px rgba(0,0,0,0.4)' : '0 4px 24px rgba(0,0,0,0.08)',
        }}
      >
        {/* Logo */}
        <div className="flex justify-center mb-8">
          <div
            className="w-12 h-12 rounded-xl flex items-center justify-center text-lg font-bold text-white"
            style={{ backgroundColor: theme.colors.primary }}
          >
            S
          </div>
        </div>

        {step === 1 ? (
          <>
            <h1 className="text-xl font-bold text-center mb-1" style={{ color: theme.colors.text }}>
              {t.login.welcome}
            </h1>
            <p className="text-sm text-center mb-6" style={{ color: theme.colors.textSub }}>
              {t.login.subtitle}
            </p>

            <form onSubmit={handleLogin} className="space-y-3">
              <div
                className="flex items-center gap-3 rounded-[11px] px-4 py-3"
                style={{
                  backgroundColor: theme.colors.surfaceAlt,
                  border: `0.5px solid ${theme.colors.border}`,
                }}
              >
                <User size={16} style={{ color: theme.colors.textHint }} />
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder={t.login.username}
                  className="flex-1 bg-transparent outline-none text-sm"
                  style={{ color: theme.colors.text }}
                />
              </div>

              <div
                className="flex items-center gap-3 rounded-[11px] px-4 py-3"
                style={{
                  backgroundColor: theme.colors.surfaceAlt,
                  border: `0.5px solid ${theme.colors.border}`,
                }}
              >
                <Lock size={16} style={{ color: theme.colors.textHint }} />
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={t.login.password}
                  className="flex-1 bg-transparent outline-none text-sm"
                  style={{ color: theme.colors.text }}
                />
                <button type="button" onClick={() => setShowPassword(!showPassword)}>
                  {showPassword ? (
                    <EyeOff size={16} style={{ color: theme.colors.textHint }} />
                  ) : (
                    <Eye size={16} style={{ color: theme.colors.textHint }} />
                  )}
                </button>
              </div>

              {error && (
                <p className="text-xs text-center" style={{ color: theme.colors.down }}>
                  {error}
                </p>
              )}

              <Button type="submit" fullWidth disabled={!username.trim() || !password.trim() || loading}>
                {loading ? t.login.signingIn : t.login.continue}
              </Button>
            </form>
          </>
        ) : (
          <>
            <h1 className="text-xl font-bold text-center mb-1" style={{ color: theme.colors.text }}>
              {t.login.checkTelegram}
            </h1>
            <p className="text-sm text-center mb-6" style={{ color: theme.colors.textSub }}>
              {t.login.otpSent}
            </p>

            <form onSubmit={handleVerify} className="space-y-4">
              <div className="flex justify-center gap-2" onPaste={handleOtpPaste}>
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
                    className="w-10 sm:w-11 h-12 text-center text-lg font-bold rounded-[9px] outline-none"
                    style={{
                      backgroundColor: theme.colors.surfaceAlt,
                      color: theme.colors.text,
                      border: `1px solid ${theme.colors.border}`,
                    }}
                  />
                ))}
              </div>

              <p
                className="text-center text-sm font-semibold tabular-nums"
                style={{
                  color: countdown <= 10 ? theme.colors.down : theme.colors.textSub,
                }}
              >
                {countdown > 0 ? t.login.remaining.replace('{seconds}', String(countdown)) : t.login.codeExpired}
              </p>

              {error && (
                <p className="text-xs text-center" style={{ color: theme.colors.down }}>
                  {error}
                </p>
              )}

              <Button
                type="submit"
                fullWidth
                disabled={otp.join('').length !== 6 || loading}
              >
                {loading ? t.login.verifying : t.login.verify}
              </Button>

              <button
                type="button"
                onClick={handleResend}
                disabled={countdown > 0}
                className="w-full text-center text-sm font-medium transition-opacity"
                style={{
                  color: countdown > 0 ? theme.colors.textHint : theme.colors.primary,
                  opacity: countdown > 0 ? 0.5 : 1,
                }}
              >
                {t.login.resend}
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  )
}
