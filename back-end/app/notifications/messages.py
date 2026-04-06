"""Bilingual Telegram message templates (EN / PT)."""

from app.core.config import settings

_MESSAGES = {
    "ping": {
        "en": "🏓 <b>Signa Ping</b>\n\nTelegram integration is working.",
        "pt": "🏓 <b>Signa Ping</b>\n\nIntegração com Telegram está funcionando.",
    },
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
    "gem_alert": {
        "en": (
            "💎 <b>GEM ALERT — {ticker}</b>\n\n"
            "📅 {date}\n"
            "Signal: <b>{action}</b> | Score: <b>{score}/100</b>\n"
            "Price: ${price} | Target: ${target} | Stop: ${stop}\n"
            "Risk/Reward: {rr}x\n\n"
            "📋 {reasoning}\n"
            "{catalyst_line}"
            "\n\n⚡ All 5 GEM conditions met"
        ),
        "pt": (
            "💎 <b>ALERTA GEM — {ticker}</b>\n\n"
            "📅 {date}\n"
            "Sinal: <b>{action}</b> | Pontuação: <b>{score}/100</b>\n"
            "Preço: ${price} | Alvo: ${target} | Stop: ${stop}\n"
            "Risco/Retorno: {rr}x\n\n"
            "📋 {reasoning}\n"
            "{catalyst_line}"
            "\n\n⚡ Todas as 5 condições GEM atendidas"
        ),
    },
    "watchlist_sell": {
        "en": (
            "{emoji} <b>WATCHLIST ALERT — {ticker}</b>\n\n"
            "📅 {date}\n"
            "Signal: <b>{action}</b> | Score: <b>{score}/100</b>\n"
            "Status: {status} | Price: ${price}\n"
            "{target_line}"
            "{bucket_line}"
            "\n📋 {reasoning}\n\n"
            "⚡ This ticker is on your watchlist — take action now."
        ),
        "pt": (
            "{emoji} <b>ALERTA FAVORITOS — {ticker}</b>\n\n"
            "📅 {date}\n"
            "Sinal: <b>{action}</b> | Pontuação: <b>{score}/100</b>\n"
            "Status: {status} | Preço: ${price}\n"
            "{target_line}"
            "{bucket_line}"
            "\n📋 {reasoning}\n\n"
            "⚡ Este ticker está nos seus favoritos — tome ação agora."
        ),
    },
    "scan_digest_header": {
        "en": "📊 <b>Signa {scan_label} Digest</b>\n\n📅 {date}\nSignals: {total} | BUYs: {buys} | GEMs: {gems}\n\n",
        "pt": "📊 <b>Resumo Signa {scan_label}</b>\n\n📅 {date}\nSinais: {total} | COMPRAs: {buys} | GEMs: {gems}\n\n",
    },
    "scan_digest_top3": {
        "en": "<b>Top 3 Signals:</b>\n",
        "pt": "<b>Top 3 Sinais:</b>\n",
    },
    "scan_digest_gem_footer": {
        "en": "\n💎 <b>{count} GEM Alert(s)</b> — check /gem for details",
        "pt": "\n💎 <b>{count} Alerta(s) GEM</b> — use /gem para detalhes",
    },
    "stop_loss": {
        "en": (
            "🚨 <b>STOP LOSS HIT — {ticker}</b>\n\n"
            "Your position hit the stop loss.\n"
            "Entry: ${entry} | Stop: ${stop} | Current: ${current}\n"
            "P&L: {pnl_pct}% (${pnl_amt}/share)\n\n"
            "⚡ Position auto-closed."
        ),
        "pt": (
            "🚨 <b>STOP LOSS ATINGIDO — {ticker}</b>\n\n"
            "Sua posição atingiu o stop loss.\n"
            "Entrada: ${entry} | Stop: ${stop} | Atual: ${current}\n"
            "P&L: {pnl_pct}% (${pnl_amt}/ação)\n\n"
            "⚡ Posição fechada automaticamente."
        ),
    },
    "target_reached": {
        "en": (
            "🎯 <b>TARGET REACHED — {ticker}</b>\n\n"
            "Your position hit the target price!\n"
            "Entry: ${entry} | Target: ${target} | Current: ${current}\n"
            "P&L: {pnl_pct}% (${pnl_amt}/share)\n\n"
            "✅ Consider taking profits."
        ),
        "pt": (
            "🎯 <b>ALVO ATINGIDO — {ticker}</b>\n\n"
            "Sua posição atingiu o preço alvo!\n"
            "Entrada: ${entry} | Alvo: ${target} | Atual: ${current}\n"
            "P&L: {pnl_pct}% (${pnl_amt}/ação)\n\n"
            "✅ Considere realizar lucros."
        ),
    },
    "pnl_milestone": {
        "en": (
            "📊 <b>P&L MILESTONE — {ticker}</b>\n\n"
            "Your position crossed {direction}{threshold}% profit.\n"
            "Entry: ${entry} | Current: ${current}\n"
            "P&L: {pnl_pct}% (${pnl_amt}/share)\n\n"
            "💡 Signal still {status} (score {score})."
        ),
        "pt": (
            "📊 <b>MARCO P&L — {ticker}</b>\n\n"
            "Sua posição cruzou {direction}{threshold}% de lucro.\n"
            "Entrada: ${entry} | Atual: ${current}\n"
            "P&L: {pnl_pct}% (${pnl_amt}/ação)\n\n"
            "💡 Sinal ainda {status} (pontuação {score})."
        ),
    },
    "signal_weakening": {
        "en": (
            "⚠️ <b>SIGNAL WEAKENING — {ticker}</b>\n\n"
            "The signal for your position has weakened.\n"
            "Previous: {prev_status} (score {prev_score}) → Now: {new_status} (score {new_score})\n\n"
            "💡 Re-evaluate your position."
        ),
        "pt": (
            "⚠️ <b>SINAL ENFRAQUECENDO — {ticker}</b>\n\n"
            "O sinal para sua posição enfraqueceu.\n"
            "Anterior: {prev_status} (pontuação {prev_score}) → Agora: {new_status} (pontuação {new_score})\n\n"
            "💡 Reavalie sua posição."
        ),
    },
    "bot_help": {
        "en": (
            "<b>🤖 Signa Bot Commands:</b>\n\n"
            "/signals — Latest signals\n"
            "/gem — GEM alerts only\n"
            "/watch — View watchlist\n"
            "/watch TICKER — Add to watchlist\n"
            "/remove TICKER — Remove from watchlist\n"
            "/score TICKER — Get score for a ticker\n"
            "/positions — Open positions with P&L\n"
            "/close TICKER PRICE — Close a position\n"
            "/status — Bot/scan status"
        ),
        "pt": (
            "<b>🤖 Comandos do Bot Signa:</b>\n\n"
            "/signals — Últimos sinais\n"
            "/gem — Apenas alertas GEM\n"
            "/watch — Ver favoritos\n"
            "/watch TICKER — Adicionar aos favoritos\n"
            "/remove TICKER — Remover dos favoritos\n"
            "/score TICKER — Ver pontuação de um ticker\n"
            "/positions — Posições abertas com P&L\n"
            "/close TICKER PREÇO — Fechar uma posição\n"
            "/status — Status do bot/varredura"
        ),
    },
    "watchdog_warning": {
        "en": (
            "<b>Signa Watchdog</b>\n\n"
            "{symbol} dropped {change}% since last check.\n"
            "Now: ${price} | Stop: ${stop}\n"
            "Sentiment: {sentiment}\n\n"
            "Brain is monitoring closely."
        ),
        "pt": (
            "<b>Signa Watchdog</b>\n\n"
            "{symbol} caiu {change}% desde a \u00faltima verifica\u00e7\u00e3o.\n"
            "Agora: ${price} | Stop: ${stop}\n"
            "Sentimento: {sentiment}\n\n"
            "O brain est\u00e1 monitorando de perto."
        ),
    },
    "watchdog_exit": {
        "en": (
            "<b>Signa Watchdog -- Brain Sold</b>\n\n"
            "{symbol} closed @ ${price}\n"
            "P&L: {pnl}%\n"
            "Reason: bearish sentiment + price drop\n"
            "Sentiment: {sentiment}"
        ),
        "pt": (
            "<b>Signa Watchdog -- Brain Vendeu</b>\n\n"
            "{symbol} fechado @ ${price}\n"
            "P&L: {pnl}%\n"
            "Motivo: sentimento bearish + queda de pre\u00e7o\n"
            "Sentimento: {sentiment}"
        ),
    },
    "watchdog_user_warning": {
        "en": (
            "<b>Signa Alert -- Watchlist</b>\n\n"
            "Signa identified unusual activity on {symbol}.\n"
            "This ticker is in your watchlist -- keep an eye on it "
            "and consider selling if needed."
        ),
        "pt": (
            "<b>Signa Alerta -- Watchlist</b>\n\n"
            "Signa identificou atividade incomum em {symbol}.\n"
            "Este ticker est\u00e1 na sua watchlist -- fique de olho "
            "e considere vender se necess\u00e1rio."
        ),
    },
    "watchdog_user_brain_sold": {
        "en": (
            "<b>Signa Alert -- Brain Sold Your Watchlist Ticker</b>\n\n"
            "Brain just sold {symbol} @ ${price} (P&L: {pnl}%).\n"
            "This ticker is in your watchlist -- your call whether "
            "to sell your real position too."
        ),
        "pt": (
            "<b>Signa Alerta -- Brain Vendeu Ticker da Watchlist</b>\n\n"
            "Brain acabou de vender {symbol} @ ${price} (P&L: {pnl}%).\n"
            "Este ticker est\u00e1 na sua watchlist -- voc\u00ea decide se "
            "quer vender sua posi\u00e7\u00e3o real tamb\u00e9m."
        ),
    },
    "brain_otp": {
        "en": (
            "🧠 <b>Signa Brain Editor</b>\n\n"
            "Access code: <code>{otp}</code>\n\n"
            "⏱ Valid for 60 seconds only.\n"
            "This grants access to edit signal rules.\n"
            "Never share this code."
        ),
        "pt": (
            "🧠 <b>Editor do Cérebro Signa</b>\n\n"
            "Código de acesso: <code>{otp}</code>\n\n"
            "⏱ Válido por 60 segundos apenas.\n"
            "Isso concede acesso para editar regras de sinais.\n"
            "Nunca compartilhe este código."
        ),
    },
}


def msg(key: str, **kwargs) -> str:
    """Get a translated message template and format it."""
    lang = settings.language if settings.language in ("en", "pt") else "en"
    template = _MESSAGES.get(key, {}).get(lang, _MESSAGES.get(key, {}).get("en", key))
    try:
        return template.format(**kwargs) if kwargs else template
    except KeyError:
        return template
