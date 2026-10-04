"""Transactional email: sign-in codes, password reset, new-address checks.

Provider by settings.email_provider:
  console  (default) logs the message instead of sending it. For development:
           the code appears in the back-end log. Never use in production.
  resend   Resend HTTP API (settings.resend_api_key). Free tier covers launch.
  smtp     any SMTP server (settings.smtp_*): Amazon SES, Brevo, Postmark,
           Gmail… Switching provider is a config change only.
settings.email_from is the sender ("Signa <no-reply@your-domain>"); the
domain must be verified with the provider.

build_code_email() is pure (subject, text, html); send_code() does the IO and
never raises: it returns False when the message could not be handed over.
"""

from __future__ import annotations

import html
import smtplib
import ssl
from email.message import EmailMessage

from loguru import logger

from app.core.config import settings

Purpose = str  # "login" | "signup" | "reset" | "email" | "exists"

_TEXT = {
    "en": {
        "subject": {"login": "Your Signa sign-in code: {code}", "signup": "Confirm your Signa account: {code}",
                    "reset": "Reset your Signa password: {code}", "email": "Confirm your email for Signa: {code}",
                    "exists": "You already have a Signa account"},
        "lead": {"login": "Use this code to sign in to Signa.", "signup": "Use this code to finish creating your Signa account.",
                 "reset": "Use this code to choose a new Signa password.", "email": "Use this code to confirm this email address for Signa.",
                 "exists": "Someone (maybe you) tried to create a Signa account with this email. You already have one: sign in, or use \"Forgot password\" if you don't remember it."},
        "expires": "It expires in {minutes} minutes.",
        "ignore": "If you didn't ask for this, you can ignore this email. Nobody can sign in without your password.",
    },
    "pt": {
        "subject": {"login": "Seu código de acesso ao Signa: {code}", "signup": "Confirme sua conta Signa: {code}",
                    "reset": "Redefina sua senha do Signa: {code}", "email": "Confirme seu e-mail no Signa: {code}",
                    "exists": "Você já tem uma conta Signa"},
        "lead": {"login": "Use este código para entrar no Signa.", "signup": "Use este código para terminar de criar sua conta Signa.",
                 "reset": "Use este código para escolher uma nova senha do Signa.", "email": "Use este código para confirmar este e-mail no Signa.",
                 "exists": "Alguém (talvez você) tentou criar uma conta Signa com este e-mail. Você já tem uma: entre, ou use \"Esqueci a senha\" se não lembrar."},
        "expires": "Ele expira em {minutes} minutos.",
        "ignore": "Se você não pediu isto, pode ignorar este e-mail. Ninguém entra sem a sua senha.",
    },
}


def build_code_email(purpose: Purpose, code: str | None, language: str = "en",
                     minutes: int = 10) -> tuple[str, str, str]:
    """(subject, plain text, html) for a code email. Pure."""
    t = _TEXT.get(language if language in _TEXT else "en")
    subject = t["subject"][purpose].format(code=code or "")
    lines = [t["lead"][purpose]]
    if code:
        lines += ["", code, "", t["expires"].format(minutes=minutes)]
    lines += ["", t["ignore"], "", "Signa"]
    text = "\n".join(lines)
    code_html = (f'<p style="font-size:30px;font-weight:700;letter-spacing:6px;margin:24px 0;'
                 f'font-family:ui-monospace,Menlo,monospace">{html.escape(code)}</p>'
                 f'<p style="color:#55665f">{html.escape(t["expires"].format(minutes=minutes))}</p>') if code else ""
    body = (f'<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:480px;'
            f'margin:0 auto;padding:24px;color:#13211b">'
            f'<p style="font-size:18px;font-weight:700;margin:0 0 16px">Signa</p>'
            f'<p>{html.escape(t["lead"][purpose])}</p>{code_html}'
            f'<p style="color:#55665f;font-size:13px;margin-top:24px">{html.escape(t["ignore"])}</p></div>')
    return subject, text, body


def _send_resend(to: str, subject: str, text: str, body: str) -> bool:
    import httpx
    r = httpx.post("https://api.resend.com/emails", timeout=15,
                   headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                   json={"from": settings.email_from, "to": [to], "subject": subject, "text": text, "html": body})
    if r.status_code >= 300:
        logger.warning(f"email: Resend refused the message ({r.status_code})")
        return False
    return True


def _send_smtp(to: str, subject: str, text: str, body: str) -> bool:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.email_from, to, subject
    msg.set_content(text)
    msg.add_alternative(body, subtype="html")
    ctx = ssl.create_default_context()
    if settings.smtp_port == 465:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=ctx, timeout=15) as s:
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
            s.starttls(context=ctx)
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
    return True


def send_code(to: str, purpose: Purpose, code: str | None, language: str = "en") -> bool:
    """Send a code email. Never raises; False when it could not be sent."""
    minutes = max(1, settings.email_code_expire_seconds // 60)
    subject, text, body = build_code_email(purpose, code, language, minutes)
    provider = (settings.email_provider or "console").lower()
    try:
        if provider == "resend" and settings.resend_api_key:
            return _send_resend(to, subject, text, body)
        if provider == "smtp" and settings.smtp_host:
            return _send_smtp(to, subject, text, body)
        if provider not in ("console", "resend", "smtp"):
            logger.warning(f"email: unknown EMAIL_PROVIDER {provider!r}, logging instead")
        # console (development): the code goes to the log, the address is masked
        masked = to[:2] + "***" + to[to.find("@"):] if "@" in to else "***"
        logger.warning(f"email (console, not sent) to {masked}: {subject}")
        return True
    except Exception as e:
        logger.warning(f"email: sending via {provider} failed: {e}")
        return False
