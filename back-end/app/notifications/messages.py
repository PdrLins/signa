"""Bilingual Telegram message templates (EN / PT)."""

from app.core.config import settings

_MESSAGES = {
    "otp": {
        "en": (
            "🔐 <b>Signa Verification Code</b>\n\n"
            "Your login code is: <code>{otp_code}</code>\n\n"
            "⏱ Valid for 30 seconds only\n"
            "Never share this code with anyone."
        ),
        "pt": (
            "🔐 <b>Código de Verificação Signa</b>\n\n"
            "Seu código de login é: <code>{otp_code}</code>\n\n"
            "⏱ Válido por 30 segundos apenas\n"
            "Nunca compartilhe este código."
        ),
    },
    # ── Per-user Telegram notifications (migration 016, Premium) ──
    "user_tg_connected": {
        "en": "✅ <b>Signa is connected</b>\n\nYour Signa notifications will arrive here. "
              "Choose which ones in the app: Profile → Notifications.",
        "pt": "✅ <b>Signa conectado</b>\n\nSuas notificações do Signa vão chegar aqui. "
              "Escolha quais no app: Perfil → Notificações.",
    },
    "user_2fa_code": {
        "en": "🔐 <b>Signa two-step sign-in</b>\n\nYour code: <code>{code}</code>\n\n"
              "Type it in the Signa app to turn on two-step sign-in. It expires in 10 minutes. "
              "If you didn't ask for this, ignore this message.",
        "pt": "🔐 <b>Verificação em duas etapas do Signa</b>\n\nSeu código: <code>{code}</code>\n\n"
              "Digite no app Signa para ativar a verificação em duas etapas. Ele expira em 10 minutos. "
              "Se você não pediu isto, ignore esta mensagem.",
    },
    "user_reset_code": {
        "en": "🔑 <b>Reset your Signa password</b>\n\nYour code: <code>{code}</code>\n\n"
              "Type it in the Signa app to choose a new password. It expires in 10 minutes. "
              "If you didn't ask for this, ignore this message: nobody can change your password without it.",
        "pt": "🔑 <b>Redefinir sua senha do Signa</b>\n\nSeu código: <code>{code}</code>\n\n"
              "Digite no app Signa para escolher uma nova senha. Ele expira em 10 minutos. "
              "Se você não pediu isto, ignore esta mensagem: ninguém troca sua senha sem ele.",
    },
    "user_2fa_on": {
        "en": "✅ <b>Two-step sign-in is on</b>\n\nFrom now on, Signa sends your sign-in codes to this chat.",
        "pt": "✅ <b>Verificação em duas etapas ativada</b>\n\nA partir de agora, o Signa envia seus códigos de acesso para este chat.",
    },
    "user_2fa_off": {
        "en": "Two-step sign-in was turned off for your Signa account. If this wasn't you, change your password now.",
        "pt": "A verificação em duas etapas foi desativada na sua conta Signa. Se não foi você, troque sua senha agora.",
    },
    "user_2fa_link_expired": {
        "en": "This link has expired or was already used. Open Signa → Profile → Two-step sign-in and start again.",
        "pt": "Este link expirou ou já foi usado. Abra o Signa → Perfil → Verificação em duas etapas e comece de novo.",
    },
    "user_tg_link_expired": {
        "en": "This link has expired or was already used. Open Signa and tap <b>Connect Telegram</b> again.",
        "pt": "Este link expirou ou já foi usado. Abra o Signa e toque em <b>Conectar Telegram</b> de novo.",
    },
    "user_tg_test": {
        "en": "🔔 <b>Signa test</b>\n\nTelegram notifications are working.",
        "pt": "🔔 <b>Teste do Signa</b>\n\nAs notificações pelo Telegram estão funcionando.",
    },
    "user_tg_header": {"en": "🔔 <b>Signa</b>", "pt": "🔔 <b>Signa</b>"},
    # Referral rewarded (migration 019, app/services/referrals.py)
    "user_tg_referral_rewarded": {
        "en": "🎉 <b>Your friend joined Signa</b>\n\n+{per_friend} stocks to follow. Thanks for inviting them!",
        "pt": "🎉 <b>Seu amigo entrou no Signa</b>\n\n+{per_friend} ações para acompanhar. Obrigado pelo convite!",
    },
    "user_tg_tomorrow": {"en": "tomorrow", "pt": "amanhã"},
    "user_tg_today": {"en": "today", "pt": "hoje"},
    "user_tg_on_date": {"en": "on {date}", "pt": "em {date}"},
    "user_tg_exdiv": {
        "en": "📅 <b>{symbol}</b> goes ex-dividend {when}{amount}",
        "pt": "📅 <b>{symbol}</b> fica ex-dividendo {when}{amount}",
    },
    "user_tg_paid": {
        "en": "💵 <b>{symbol}</b> pays its dividend today{amount}",
        "pt": "💵 <b>{symbol}</b> paga o dividendo hoje{amount}",
    },
    "user_tg_raise": {
        "en": "📈 <b>{symbol}</b> raised its dividend {pct} ({old} → {new} per share)",
        "pt": "📈 <b>{symbol}</b> aumentou o dividendo {pct} ({old} → {new} por ação)",
    },
    "user_tg_cut": {
        "en": "📉 <b>{symbol}</b> cut its dividend {pct} ({old} → {new} per share)",
        "pt": "📉 <b>{symbol}</b> cortou o dividendo {pct} ({old} → {new} por ação)",
    },
    "user_tg_earnings": {
        "en": "📊 <b>{symbol}</b> reports earnings {when}{move}",
        "pt": "📊 <b>{symbol}</b> divulga resultados {when}{move}",
    },
    "user_tg_earnings_move": {
        "en": " — usually moves ±{pct}",
        "pt": " — costuma variar ±{pct}",
    },
    "user_tg_analyst": {
        "en": "🧐 <b>{symbol}</b>: {firm} {action}{grades}",
        "pt": "🧐 <b>{symbol}</b>: {firm} {action}{grades}",
    },
    "user_tg_analyst_up": {"en": "upgraded", "pt": "elevou"},
    "user_tg_analyst_down": {"en": "downgraded", "pt": "rebaixou"},
    "user_tg_analyst_init": {"en": "started coverage", "pt": "iniciou cobertura"},
    "user_tg_analyst_other": {"en": "kept its rating", "pt": "manteve a recomendação"},
    "user_tg_check": {
        "en": "🔎 <b>{symbol}</b>: {n} Signa check(s) changed",
        "pt": "🔎 <b>{symbol}</b>: {n} checagem(ns) do Signa mudou(aram)",
    },
    "user_tg_economy": {"en": "🏦 {title} tomorrow", "pt": "🏦 {title} amanhã"},
    "user_tg_economy_boc_rate": {"en": "Bank of Canada rate decision", "pt": "Decisão de juros do Banco do Canadá"},
    "user_tg_economy_fed_rate": {"en": "Fed rate decision", "pt": "Decisão de juros do Fed"},
    "user_tg_economy_us_cpi": {"en": "US inflation (CPI)", "pt": "Inflação dos EUA (CPI)"},
    "user_tg_economy_ca_cpi": {"en": "Canada inflation (CPI)", "pt": "Inflação do Canadá (CPI)"},
    "user_tg_big_move": {
        "en": "⚡ <b>{symbol}</b> is {pct} today",
        "pt": "⚡ <b>{symbol}</b> está {pct} hoje",
    },
    "user_tg_alert_above": {
        "en": "🎯 <b>{symbol}</b> reached {target} (now {price})",
        "pt": "🎯 <b>{symbol}</b> chegou a {target} (agora {price})",
    },
    "user_tg_alert_below": {
        "en": "🎯 <b>{symbol}</b> fell to {target} (now {price})",
        "pt": "🎯 <b>{symbol}</b> caiu para {target} (agora {price})",
    },
}


def msg(key: str, **kwargs) -> str:
    """Get a translated message template and format it."""
    lang = settings.language if settings.language in ("en", "pt") else "en"
    template = _MESSAGES.get(key, {}).get(lang, _MESSAGES.get(key, {}).get("en", key))
    # Auto-inject timestamp if not provided
    if "timestamp" not in kwargs:
        from datetime import datetime
        import pytz
        et = datetime.now(pytz.timezone("America/New_York"))
        kwargs["timestamp"] = et.strftime("%b %d, %I:%M %p ET")
    # Default context to empty string
    if "context" not in kwargs:
        kwargs["context"] = ""
    try:
        return template.format(**kwargs) if kwargs else template
    except KeyError:
        return template


def is_quiet_hours() -> bool:
    """Check if current time is within notification quiet hours.

    Compared in minutes-since-midnight so the window can be set at
    minute granularity (e.g. 18:00 → 06:30). When end < start the
    window spans midnight.
    """
    if not settings.notify_quiet_enabled:
        return False
    from datetime import datetime
    import pytz
    et = datetime.now(pytz.timezone("America/New_York"))
    now_mins = et.hour * 60 + et.minute
    start_mins = settings.notify_quiet_start * 60 + settings.notify_quiet_start_minute
    end_mins = settings.notify_quiet_end * 60 + settings.notify_quiet_end_minute
    if start_mins > end_mins:  # spans midnight
        return now_mins >= start_mins or now_mins < end_mins
    return start_mins <= now_mins < end_mins


def msg_for(lang: str | None, key: str, **kwargs) -> str:
    """A template in a given user's language (per-user notifications). No
    timestamp/context injection; unknown placeholders leave the template as is."""
    lang = lang if lang in ("en", "pt") else "en"
    template = _MESSAGES.get(key, {}).get(lang, _MESSAGES.get(key, {}).get("en", key))
    try:
        return template.format(**kwargs) if kwargs else template
    except KeyError:
        return template
