'use client'

import { useCallback, useEffect, useId, useMemo, useState } from 'react'
import Link from 'next/link'
import {
  Bell, HelpCircle, Landmark, LogOut, Plug, ReceiptText, ScrollText, SlidersHorizontal, Trash2, Upload,
} from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore, type Locale } from '@/store/i18nStore'
import { useAuthStore } from '@/store/authStore'
import { useToast } from '@/hooks/useToast'
import { useAccess } from '@/hooks/useAccess'
import { useProfile, useProfileOptions, useUpdateProfile } from '@/hooks/useProfile'
import { fill } from '@/lib/insights'
import { countryName, currencyName } from '@/lib/intlNames'
import { isMigrationRequired, trackerErrorText } from '@/lib/trackerErrors'
import {
  LinkRow, LoadError, MigrationNotice, SectionCard, Segmented, SoonBadge, ToggleRow, TrackerHeader,
  useButtonStyles, useFieldStyle,
} from '@/components/profile/ui'
import { Skeleton } from '@/components/ui/Skeleton'
import { SlotMeter } from '@/components/upgrade/SlotMeter'
import { ThemePicker } from '@/components/profile/ThemePicker'
import { usePrivacyStore } from '@/store/privacyStore'
import type { ProfileUpdate, TaxView } from '@/types/profile'

export default function ProfilePage() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tp = t.profile
  const locale = useI18nStore((s) => s.locale)
  const setLocale = useI18nStore((s) => s.setLocale)
  const logout = useAuthStore((s) => s.logout)
  const toast = useToast()
  const qc = useQueryClient()
  const { can } = useAccess()
  const q = useProfile()
  const opts = useProfileOptions()
  const update = useUpdateProfile()
  const f = useFieldStyle()
  const btn = useButtonStyles()
  const ids = { name: useId(), ccy: useId(), cmp: useId(), country: useId() }
  const amountsHidden = usePrivacyStore((s) => s.hidden)
  const toggleHidden = usePrivacyStore((s) => s.toggle)
  const loadPrivacy = usePrivacyStore((s) => s.load)
  useEffect(() => { loadPrivacy() }, [loadPrivacy])

  const profile = q.data
  const [name, setName] = useState('')
  useEffect(() => { setName(profile?.display_name ?? '') }, [profile?.display_name])
  const [deleteStep, setDeleteStep] = useState<'idle' | 'confirm' | 'unavailable'>('idle')

  const save = useCallback((patch: ProfileUpdate) => {
    update.mutate(patch, {
      onSuccess: () => {
        toast.show(tp.saved, 'success', 2000)
        qc.invalidateQueries({ queryKey: ['auth', 'me'] })
      },
      onError: (e) => toast.show(trackerErrorText(e, t), 'error'),
    })
  }, [update, toast, tp.saved, qc, t])

  const saveName = () => {
    const v = name.trim()
    if ((profile?.display_name ?? '') === v) return
    save({ display_name: v || null })
  }

  const changeLanguage = (l: Locale) => {
    setLocale(l) // instant UI switch; the profile keeps the same value for iOS / Telegram
    save({ language: l })
  }

  const countries = useMemo(
    () => (opts.data?.countries ?? [])
      .map((c) => ({ code: c, name: countryName(c, locale) }))
      .sort((a, b) => a.name.localeCompare(b.name, locale)),
    [opts.data, locale],
  )
  const currencies = useMemo(() => opts.data?.currencies ?? [], [opts.data])
  const convertible = useMemo(() => (opts.data?.convertible_currencies ?? []).join(', '), [opts.data])
  const taxCountries = useMemo(() => new Set(opts.data?.tax_view_countries ?? ['CA', 'US']), [opts.data])

  if (q.isLoading) {
    return (
      <div className="space-y-4" aria-busy="true">
        <Skeleton height={48} width="40%" />
        <Skeleton height={160} width="100%" />
        <Skeleton height={160} width="100%" />
      </div>
    )
  }

  const migration = isMigrationRequired(q.error)
  const busy = update.isPending
  const inTaxCountry = !!profile?.country && taxCountries.has(profile.country)

  const signOut = () => {
    logout()
    window.location.href = '/login'
  }

  return (
    <div className="space-y-4 pb-4 min-w-0 max-w-3xl">
      <TrackerHeader title={tp.title} subtitle={tp.subtitle} />

      {migration && <MigrationNotice />}
      {!!q.error && !migration && <LoadError message={trackerErrorText(q.error, t)} onRetry={() => q.refetch()} />}

      {profile && (
        <>
          <SectionCard title={tp.sections.you}>
            <div className={f.label} style={{ color: f.labelColor }}>
              <label htmlFor={ids.name}>{tp.displayName}</label>
              <div className="flex gap-2">
                <input id={ids.name} value={name} maxLength={60} placeholder={tp.displayNamePlaceholder}
                  autoComplete="nickname" onChange={(e) => setName(e.target.value)} onBlur={saveName}
                  onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); saveName() } }}
                  className={f.input} style={f.style} />
              </div>
            </div>
            <dl className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-[13px]">
              {profile.username && (
                <div className="min-w-0"><dt style={{ color: theme.colors.textSub }}>{tp.username}</dt>
                  <dd className="truncate" style={{ color: theme.colors.text }}>{profile.username}</dd></div>
              )}
              {profile.email && (
                <div className="min-w-0"><dt style={{ color: theme.colors.textSub }}>{tp.email}</dt>
                  <dd className="truncate" style={{ color: theme.colors.text }}>{profile.email}</dd></div>
              )}
              <div className="min-w-0"><dt style={{ color: theme.colors.textSub }}>{tp.plan}</dt>
                <dd style={{ color: theme.colors.text }}>{t.access.levels[profile.access_level]}</dd></div>
            </dl>
            <div className="flex flex-wrap items-end justify-between gap-3">
              <SlotMeter />
              <Link href="/pricing" className="text-[13px] font-medium min-h-[44px] inline-flex items-center rounded focus-visible:outline focus-visible:outline-2"
                style={{ color: theme.colors.primary, outlineColor: theme.colors.primary }}>
                {t.pricing.seePlans}
              </Link>
            </div>
          </SectionCard>

          <SectionCard title={tp.sections.display}>
            <div className="flex flex-col gap-1">
              <span className="text-[12px]" style={{ color: theme.colors.textSub }}>{tp.language}</span>
              <Segmented<Locale> label={tp.language} value={locale} disabled={busy}
                options={[{ value: 'en', label: tp.languages.en }, { value: 'pt', label: tp.languages.pt }]}
                onChange={changeLanguage} />
            </div>
            <ToggleRow label={tp.hideAmounts} desc={tp.hideAmountsHelp} checked={amountsHidden} onChange={() => toggleHidden()} />
            <div className="flex flex-col gap-1.5">
              <span className="text-[12px]" style={{ color: theme.colors.textSub }}>{t.settings.themeLabel}</span>
              <ThemePicker />
            </div>
          </SectionCard>

          <SectionCard title={tp.sections.money}>
            <label htmlFor={ids.ccy} className={f.label} style={{ color: f.labelColor }}>
              {tp.homeCurrency}
              <select id={ids.ccy} value={profile.home_currency} disabled={busy || !currencies.length}
                onChange={(e) => save({ home_currency: e.target.value })} className={f.input} style={f.style}>
                {(currencies.length ? currencies : [profile.home_currency]).map((c) => (
                  <option key={c} value={c}>{currencyName(c, locale)}</option>
                ))}
              </select>
              {convertible && <span style={{ color: theme.colors.textHint }}>{fill(tp.homeCurrencyHelp, { list: convertible })}</span>}
            </label>
            <ToggleRow label={tp.nativeCurrency} desc={tp.nativeCurrencyHelp} checked={profile.holdings_native_currency}
              disabled={busy} onChange={(v) => save({ holdings_native_currency: v })} />
            <label htmlFor={ids.cmp} className={f.label} style={{ color: f.labelColor }}>
              {tp.compareWith}
              <select id={ids.cmp} value={profile.compare_index ?? ''} disabled={busy}
                onChange={(e) => save({ compare_index: e.target.value || null })} className={f.input} style={f.style}>
                <option value="">{tp.compareOff}</option>
                {(opts.data?.compare_indexes ?? []).map((c) => (
                  <option key={c.symbol} value={c.symbol}>{c.name} ({c.symbol})</option>
                ))}
              </select>
              <span style={{ color: theme.colors.textHint }}>{tp.compareHelp}</span>
            </label>
          </SectionCard>

          <SectionCard title={tp.sections.country}>
            <label htmlFor={ids.country} className={f.label} style={{ color: f.labelColor }}>
              {tp.country}
              <select id={ids.country} value={profile.country ?? ''} disabled={busy}
                onChange={(e) => save({ country: e.target.value || null })} className={f.input} style={f.style}>
                <option value="">{tp.countryNone}</option>
                {countries.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
              </select>
              <span style={{ color: theme.colors.textHint }}>{tp.countryHelp}</span>
            </label>
            {profile.tax_view_available ? (
              <div className="flex flex-col gap-1">
                <span className="text-[12px]" style={{ color: theme.colors.textSub }}>{tp.showDividends}</span>
                <Segmented<TaxView> label={tp.showDividends} value={profile.dividend_tax_view} disabled={busy}
                  options={[{ value: 'after', label: tp.afterTax }, { value: 'before', label: tp.beforeTax }]}
                  onChange={(v) => save({ dividend_tax_view: v })} />
              </div>
            ) : (
              <p className="text-[13px] flex flex-wrap items-center gap-2" style={{ color: theme.colors.textSub }}>
                {inTaxCountry ? tp.taxPremiumOnly : tp.taxCountryOnly}
                {inTaxCountry && <SoonBadge label={t.tracker.premium} tone="primary" />}
              </p>
            )}
          </SectionCard>
        </>
      )}

      {can('area.holdings') && (
        <SectionCard title={tp.sections.portfolios}>
          <LinkRow href="/profile/accounts" icon={Landmark} label={tp.portfolios} desc={tp.portfoliosDesc} />
        </SectionCard>
      )}

      <SectionCard title={tp.sections.notifications}>
        <LinkRow href="/profile/notifications" icon={Bell} label={tp.notificationsLink} desc={tp.notificationsDesc} />
      </SectionCard>

      <SectionCard title={tp.sections.data}>
        <div className="flex flex-col gap-2">
          {can('area.holdings') && (
            <LinkRow href="/profile/transactions" icon={ReceiptText} label={tp.transactions} desc={tp.transactionsDesc} />
          )}
          {can('action.import.csv') && (
            <LinkRow href="/profile/transactions?import=1" icon={Upload} label={tp.import} desc={tp.importDesc} />
          )}
        </div>
      </SectionCard>

      {can('area.brain') && (
        <SectionCard title={tp.sections.brain}>
          <div className="flex flex-col gap-2">
            <LinkRow href="/brain/settings" icon={SlidersHorizontal} label={t.nav.brainSettings} desc={tp.brainSettingsDesc} />
            {can('area.integrations') && <LinkRow href="/integrations" icon={Plug} label={t.nav.integrations} desc={t.settingsLinks.integrations} />}
            {can('area.logs') && <LinkRow href="/logs" icon={ScrollText} label={t.nav.logs} desc={t.settingsLinks.logs} />}
          </div>
        </SectionCard>
      )}

      <SectionCard title={tp.sections.about}>
        <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{t.tracker.notAdvice}</p>
        {can('area.how_it_works') && (
          <LinkRow href="/how-it-works" icon={HelpCircle} label={t.settingsLinks.howItWorksTitle} desc={t.settingsLinks.howItWorks} />
        )}
      </SectionCard>

      <SectionCard title={tp.sections.account}>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={signOut} className={btn.secondary.className} style={btn.secondary.style}>
            <LogOut size={16} aria-hidden="true" />{tp.signOut}
          </button>
          {deleteStep === 'idle' && (
            <button type="button" onClick={() => setDeleteStep('confirm')} className={btn.danger.className} style={btn.danger.style}>
              <Trash2 size={16} aria-hidden="true" />{tp.deleteAccount}
            </button>
          )}
        </div>
        {deleteStep === 'confirm' && (
          <div role="alertdialog" aria-labelledby="delete-title" aria-describedby="delete-body"
            className="rounded-xl p-3 flex flex-col gap-2" style={{ border: `1px solid ${theme.colors.down}` }}>
            <p id="delete-title" className="text-[14px] font-semibold" style={{ color: theme.colors.text }}>{tp.deleteTitle}</p>
            <p id="delete-body" className="text-[13px]" style={{ color: theme.colors.textSub }}>{tp.deleteBody}</p>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={() => setDeleteStep('unavailable')} className={btn.danger.className}
                style={{ ...btn.danger.style, border: `1px solid ${theme.colors.down}` }}>
                {tp.deleteConfirm}
              </button>
              <button type="button" onClick={() => setDeleteStep('idle')} className={btn.secondary.className} style={btn.secondary.style}>
                {t.tracker.cancel}
              </button>
            </div>
          </div>
        )}
        {deleteStep === 'unavailable' && (
          <p role="status" className="text-[13px] rounded-xl p-3" style={{ color: theme.colors.text, backgroundColor: theme.colors.surfaceAlt }}>
            {tp.deleteUnavailable}
          </p>
        )}
      </SectionCard>
    </div>
  )
}
