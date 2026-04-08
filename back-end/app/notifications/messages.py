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
            "{symbol} -- P&L: {pnl}% (total)\n"
            "Now: ${price} | Stop: ${stop}\n"
            "Sentiment: {sentiment}\n"
            "Reason: {reason}\n"
            "{context}\n\n"
            "Brain is monitoring closely.\n"
            '<a href="https://ca.finance.yahoo.com/quote/{symbol}">View on Yahoo Finance</a>\n'
            "<i>{timestamp}</i>"
        ),
        "pt": (
            "<b>Signa Watchdog</b>\n\n"
            "{symbol} -- P&L: {pnl}% (total)\n"
            "Agora: ${price} | Stop: ${stop}\n"
            "Sentimento: {sentiment}\n"
            "Motivo: {reason}\n"
            "{context}\n\n"
            "O brain esta monitorando de perto.\n"
            '<a href="https://ca.finance.yahoo.com/quote/{symbol}">Ver no Yahoo Finance</a>\n'
            "<i>{timestamp}</i>"
        ),
    },
    "watchdog_exit": {
        "en": (
            "<b>Signa Watchdog -- Brain Sold</b>\n\n"
            "{symbol} closed @ ${price}\n"
            "P&L: {pnl}%\n"
            "Reason: bearish sentiment + price drop\n"
            "Sentiment: {sentiment}\n"
            '{context}\n'
            '<a href="https://ca.finance.yahoo.com/quote/{symbol}">View on Yahoo Finance</a>\n'
            "<i>{timestamp}</i>"
        ),
        "pt": (
            "<b>Signa Watchdog -- Brain Vendeu</b>\n\n"
            "{symbol} fechado @ ${price}\n"
            "P&L: {pnl}%\n"
            "Motivo: sentimento bearish + queda de preco\n"
            "Sentimento: {sentiment}\n"
            '{context}\n'
            '<a href="https://ca.finance.yahoo.com/quote/{symbol}">Ver no Yahoo Finance</a>\n'
            "<i>{timestamp}</i>"
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
    "brain_buy": {
        "en": (
            "<b>Brain BUY -- {symbol}</b>\n\n"
            "Score: <b>{score}/100</b> | Bucket: {bucket}\n"
            "Tier: <b>T{tier}</b> ({trust}% position size)\n"
            "Entry: ${price} | Target: ${target} | Stop: ${stop}\n"
            "R/R: {rr}x\n\n"
            "Brain auto-picked this ticker.\n"
            '<a href="https://ca.finance.yahoo.com/quote/{symbol}">View on Yahoo Finance</a>\n'
            "<i>{timestamp}</i>"
        ),
        "pt": (
            "<b>Brain COMPRA -- {symbol}</b>\n\n"
            "Score: <b>{score}/100</b> | Bucket: {bucket}\n"
            "Tier: <b>T{tier}</b> ({trust}% do tamanho)\n"
            "Entrada: ${price} | Alvo: ${target} | Stop: ${stop}\n"
            "R/R: {rr}x\n\n"
            "Brain selecionou este ticker automaticamente.\n"
            '<a href="https://ca.finance.yahoo.com/quote/{symbol}">Ver no Yahoo Finance</a>\n'
            "<i>{timestamp}</i>"
        ),
    },
    "brain_sell": {
        "en": (
            "<b>Brain SELL -- {symbol}</b>\n\n"
            "Exit: ${price} | P&L: {pnl}%\n"
            "Reason: {reason}\n"
            "Entry score: {entry_score} | Exit score: {exit_score}\n\n"
            "{verdict}\n"
            '<a href="https://ca.finance.yahoo.com/quote/{symbol}">View on Yahoo Finance</a>\n'
            "<i>{timestamp}</i>"
        ),
        "pt": (
            "<b>Brain VENDA -- {symbol}</b>\n\n"
            "Saida: ${price} | P&L: {pnl}%\n"
            "Motivo: {reason}\n"
            "Score entrada: {entry_score} | Score saida: {exit_score}\n\n"
            "{verdict}\n"
            '<a href="https://ca.finance.yahoo.com/quote/{symbol}">Ver no Yahoo Finance</a>\n'
            "<i>{timestamp}</i>"
        ),
    },
    "budget_threshold": {
        "en": (
            "<b>💰 AI Budget Alert -- {provider}</b>\n\n"
            "Spending: <b>${spend}</b> of ${limit} ({pct}%)\n"
            "Threshold crossed: <b>{threshold}%</b>\n\n"
            "{threshold_msg}\n"
            "<i>{timestamp}</i>"
        ),
        "pt": (
            "<b>💰 Alerta de Orcamento IA -- {provider}</b>\n\n"
            "Gasto: <b>${spend}</b> de ${limit} ({pct}%)\n"
            "Limite atingido: <b>{threshold}%</b>\n\n"
            "{threshold_msg}\n"
            "<i>{timestamp}</i>"
        ),
    },
    "ai_failure_rate": {
        "en": (
            "<b>⚠ AI Failure Rate High</b>\n\n"
            "Scan: <b>{scan_type}</b>\n"
            "Failed: <b>{failed}/{total}</b> AI candidates ({pct}%)\n"
            "Top errors: {errors}\n\n"
            "Brain trust may be reduced this scan. Investigate provider health.\n"
            "<i>{timestamp}</i>"
        ),
        "pt": (
            "<b>⚠ Taxa de Falha IA Alta</b>\n\n"
            "Scan: <b>{scan_type}</b>\n"
            "Falhou: <b>{failed}/{total}</b> candidatos IA ({pct}%)\n"
            "Erros principais: {errors}\n\n"
            "Confianca do brain pode estar reduzida neste scan. Investigue saude dos providers.\n"
            "<i>{timestamp}</i>"
        ),
    },
    "brain_pending_review": {
        "en": (
            "<b>⚠ Brain Flagged for Review -- {symbol}</b>\n\n"
            "Pre-market signal turned <b>{action}</b> (score {entry_score} → {exit_score})\n"
            "Reason: {reason}\n\n"
            "Market is closed. Will re-check at open (9:30am ET):\n"
            "• Still bad → sell at open\n"
            "• Recovered → keep position\n\n"
            '<a href="https://ca.finance.yahoo.com/quote/{symbol}">View on Yahoo Finance</a>\n'
            "<i>{timestamp}</i>"
        ),
        "pt": (
            "<b>⚠ Brain Sinalizado para Revisao -- {symbol}</b>\n\n"
            "Sinal pre-market virou <b>{action}</b> (score {entry_score} → {exit_score})\n"
            "Motivo: {reason}\n\n"
            "Mercado fechado. Vai re-checar na abertura (9:30am ET):\n"
            "• Ainda ruim → vende na abertura\n"
            "• Recuperou → mantem posicao\n\n"
            '<a href="https://ca.finance.yahoo.com/quote/{symbol}">Ver no Yahoo Finance</a>\n'
            "<i>{timestamp}</i>"
        ),
    },
    "brain_review_cleared": {
        "en": (
            "<b>✅ Brain Review Cleared -- {symbol}</b>\n\n"
            "Signal recovered to <b>{action}</b> (score {entry_score} → {exit_score})\n"
            "Pre-market scare was a false alarm. Position kept.\n\n"
            '<a href="https://ca.finance.yahoo.com/quote/{symbol}">View on Yahoo Finance</a>\n'
            "<i>{timestamp}</i>"
        ),
        "pt": (
            "<b>✅ Revisao do Brain Limpa -- {symbol}</b>\n\n"
            "Sinal recuperou para <b>{action}</b> (score {entry_score} → {exit_score})\n"
            "Susto pre-market foi alarme falso. Posicao mantida.\n\n"
            '<a href="https://ca.finance.yahoo.com/quote/{symbol}">Ver no Yahoo Finance</a>\n'
            "<i>{timestamp}</i>"
        ),
    },
    "watchdog_force_sell": {
        "en": (
            "<b>Signa Watchdog -- FORCE SELL</b>\n\n"
            "{symbol} force-closed @ ${price}\n"
            "P&L: {pnl}%\n"
            "Reason: {reason}\n\n"
            "This was an emergency exit -- no sentiment check needed.\n"
            '<a href="https://ca.finance.yahoo.com/quote/{symbol}">View on Yahoo Finance</a>\n'
            "<i>{timestamp}</i>"
        ),
        "pt": (
            "<b>Signa Watchdog -- VENDA FORCADA</b>\n\n"
            "{symbol} fechado forcadamente @ ${price}\n"
            "P&L: {pnl}%\n"
            "Motivo: {reason}\n\n"
            "Esta foi uma saida de emergencia -- sem verificacao de sentimento.\n"
            '<a href="https://ca.finance.yahoo.com/quote/{symbol}">Ver no Yahoo Finance</a>\n'
            "<i>{timestamp}</i>"
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
    """Check if current time is within notification quiet hours."""
    if not settings.notify_quiet_enabled:
        return False
    from datetime import datetime
    import pytz
    et = datetime.now(pytz.timezone("America/New_York"))
    hour = et.hour
    start = settings.notify_quiet_start
    end = settings.notify_quiet_end
    if start > end:  # e.g., 18-6 spans midnight
        return hour >= start or hour < end
    return start <= hour < end
