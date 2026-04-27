"""Brain wallet — the virtual cash pool that backs every brain trade.

============================================================
WHAT THIS MODULE IS
============================================================

Before Day 15, the brain's virtual portfolio implicitly traded 1 share
per signal. A +5% win on a $5 stock realized $0.25, the same % on a
$1000 stock realized $50, and they aggregated as if those numbers were
comparable. Dollar P&L was meaningless — it tracked nothing real.

This module replaces the 1-share pretense with a wallet: the user deposits
cash (default $10,000), every new brain trade sizes a position as a % of
wallet balance, and the realized dollar P&L now scales with capital. A
5% win on a 10%-sized position moves the wallet 0.5%; the brain can
compound, and risk is actually measurable (a -5% loss = -0.5% of wallet,
not "-$0.43 somewhere").

============================================================
WHERE THE WALLET SITS IN THE SYSTEM
============================================================

Two tables: `brain_wallet` (singleton per user, holds balance +
collateral_reserved) and `wallet_transactions` (append-only ledger of
every deposit/withdraw/buy/sell/short). The wallet is mutated ONLY
through this module — virtual_portfolio.py calls these helpers when it
opens or closes a trade, and app/api/v1/wallet.py calls them on user
deposit/withdraw requests.

Legacy pre-wallet trades (`is_wallet_trade = False` on virtual_trades)
run to completion on the old per-share math and do NOT touch the wallet.
Only wallet trades (`is_wallet_trade = True`) settle through here.

============================================================
SIZING RULES (see calc_position_size_usd)
============================================================

  Tier 1 (trust_multiplier 1.0) → balance × 10%
  Tier 1 (trust_multiplier 0.5) → balance × 5%  (existing downgrade path)
  Tier 2/3 (trust_multiplier 0.5) → balance × 5%
  Hard cap: balance × 15% (matches kelly.MAX_POSITION_PCT)
  Below $100 balance → return 0 (caller skips the entry)

Shorts always use Tier-1 sizing (10% of balance) and reserve 100% of
position value as collateral until they cover.

============================================================
SHORT COLLATERAL MATH
============================================================

  On SHORT_OPEN (reserve_for_short_open):
      balance              -= allocation_usd
      collateral_reserved  += allocation_usd
      (user's total value unchanged; money moved from 'free' to 'locked')

  On SHORT_COVER (release_for_short_cover):
      balance              += original_allocation_usd + pnl_usd
      collateral_reserved  -= original_allocation_usd
      (if the short was profitable, pnl_usd is positive — wallet grew;
       if it lost, pnl_usd is negative — wallet shrank)

============================================================
ATOMICITY
============================================================

Supabase's Python client doesn't expose real DB transactions. Every
mutation here follows the same best-effort pattern:

  1. Read current wallet row
  2. Compute new balance + collateral
  3. UPDATE brain_wallet with the new values
  4. INSERT wallet_transactions audit row (with snapshot of post-update state)

If step 4 fails after step 3 succeeds, we log loudly — the wallet state
is still correct, but the audit row is missing. The caller (trade insert
path) should also log the failure so the ledger can be reconstructed
from virtual_trades if needed.

============================================================
INVARIANTS
============================================================

  balance >= 0 at all times (clamped if float math pushes it below 0)
  collateral_reserved >= 0 at all times (same clamp)
  initial_deposit is set on the FIRST deposit and never reset
  total_deposited >= total_withdrawn (can't overdraw)
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from enum import Enum
from typing import Any

from loguru import logger

from app.core.config import settings
from app.db import queries as db_queries
from app.db.supabase import get_client, with_retry


class TxnType(str, Enum):
    """Canonical names for wallet_transactions.transaction_type.

    Kept in sync with the frontend `WalletTransaction['transaction_type']`
    literal union. Adding a new type requires updating both. Inheriting
    from str lets the values be written directly to the DB VARCHAR column
    without an explicit .value lookup.
    """
    DEPOSIT = "DEPOSIT"
    WITHDRAW = "WITHDRAW"
    BUY = "BUY"
    SELL = "SELL"
    SHORT_OPEN = "SHORT_OPEN"
    SHORT_COVER = "SHORT_COVER"
    LEGACY_SELL = "LEGACY_SELL"
    LEGACY_COVER = "LEGACY_COVER"
    LEGACY_BASELINE = "LEGACY_BASELINE"


# ── In-process locking ────────────────────────────────────────────────
#
# Signa runs as a single Python process, so all wallet mutations (scan
# BUYs/closes, watchdog force-closes, user API deposits/withdrawals)
# serialize through one event loop + occasional to_thread calls. A
# per-user reentrant lock is enough to prevent read-modify-write races
# within the process. Cross-process atomicity (multi-worker deploys)
# would require a Postgres `UPDATE … RETURNING` rewrite — flagged as
# a known limitation for now; Signa does not run multi-worker today.
_user_locks: dict[str, threading.RLock] = {}
_user_locks_lock = threading.Lock()


def _get_user_lock(uid: str) -> threading.RLock:
    with _user_locks_lock:
        lock = _user_locks.get(uid)
        if lock is None:
            lock = threading.RLock()
            _user_locks[uid] = lock
        return lock


@contextmanager
def _user_lock(uid: str):
    """Serialize wallet mutations for a single user across threads.

    Reentrant so a caller that already holds the lock (e.g. deposit
    calling get_wallet which reads but never mutates) doesn't deadlock.
    """
    lock = _get_user_lock(uid)
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


class LegacySnapshotFailed(RuntimeError):
    """Raised when first-deposit legacy snapshot cannot be computed.

    Signals to the API layer that the request should be retried rather
    than silently baselining at cash-only (which would inflate ROI as
    legacy positions liquidate). Mapped to HTTP 503.
    """


# ── Helpers ─────────────────────────────────────────────────────────

def _resolve_user_id(user_id: str | None) -> str | None:
    """Default to the singleton brain user when user_id is not passed.

    The brain runs against one user (see queries.get_brain_user_id). API
    routes pass the authenticated user's id explicitly; scan-triggered
    wallet mutations fall through to the brain user.
    """
    if user_id:
        return user_id
    return db_queries.get_brain_user_id()


def _clamp_nonnegative(value: float, label: str, symbol: str = "") -> float:
    """Clamp float-math noise into a non-negative value and log any underflow.

    A legitimate bug would push negative by a large amount — a $100 negative
    balance isn't "float noise". A $0.00000003 underflow from repeated
    adds is. We log both at different levels so neither is lost.
    """
    if value >= 0:
        return value
    # Tight tolerance for float precision noise
    if value > -1e-6:
        return 0.0
    logger.warning(
        f"Wallet {label} went negative (${value:.6f}){' for ' + symbol if symbol else ''} — "
        f"clamping to 0. Investigate the caller's math."
    )
    return 0.0


# ── Wallet read / lazy-create ───────────────────────────────────────

@with_retry
def get_wallet(user_id: str | None = None) -> dict | None:
    """Fetch the wallet row, lazy-creating a zeroed one if missing.

    Returns None only when there is no user at all (fresh install before
    signup). Normally returns the dict form of the brain_wallet row.

    Safe against a concurrent first-touch race: `upsert` with
    `ignore_duplicates=True` is a no-op when the row already exists, so
    two parallel callers cannot hit the UNIQUE(user_id) constraint. A
    SELECT confirms the final state.
    """
    uid = _resolve_user_id(user_id)
    if not uid:
        return None

    db = get_client()
    result = db.table("brain_wallet").select("*").eq("user_id", uid).limit(1).execute()
    if result.data:
        return result.data[0]

    try:
        db.table("brain_wallet").upsert({
            "user_id": uid,
            "balance": 0,
            "collateral_reserved": 0,
            "initial_deposit": 0,
            "total_deposited": 0,
            "total_withdrawn": 0,
        }, on_conflict="user_id", ignore_duplicates=True).execute()
    except Exception as e:
        logger.warning(f"brain_wallet upsert raced or failed for user {uid}: {e}")

    confirm = db.table("brain_wallet").select("*").eq("user_id", uid).limit(1).execute()
    if confirm.data:
        logger.info(f"Lazy-created brain_wallet for user {uid}")
        return confirm.data[0]
    logger.error(f"brain_wallet insert+reread BOTH returned no rows for user {uid}")
    return None


@with_retry
def _write_transaction(
    user_id: str,
    transaction_type: str,
    amount: float,
    balance_after: float,
    collateral_after: float,
    trade_id: str | None = None,
    symbol: str | None = None,
    shares: float | None = None,
    price: float | None = None,
    description: str | None = None,
) -> None:
    """Append one row to wallet_transactions. Best-effort — logs on failure.

    `amount` is the signed change to balance (debits negative, credits positive).
    `balance_after` and `collateral_after` are the POST-mutation snapshots so
    state at any point in time can be reconstructed from the ledger alone.
    """
    try:
        get_client().table("wallet_transactions").insert({
            "user_id": user_id,
            "transaction_type": transaction_type,
            "amount": round(amount, 4),
            "balance_after": round(balance_after, 4),
            "collateral_after": round(collateral_after, 4),
            "trade_id": trade_id,
            "symbol": symbol,
            "shares": round(shares, 6) if shares is not None else None,
            "price": round(price, 4) if price is not None else None,
            "description": description,
        }).execute()
    except Exception as e:
        # Balance has already been updated at this point. Log loudly;
        # never raise (we must not roll back wallet state because the
        # audit insert failed — the ledger can be reconstructed from
        # virtual_trades).
        logger.error(
            f"wallet_transactions insert FAILED ({transaction_type} {amount:+.2f} "
            f"for {symbol or user_id}): {e}. Wallet state IS updated; ledger is now "
            f"out of sync — reconstruct from virtual_trades if needed."
        )


@with_retry
def _apply_update(
    user_id: str,
    new_balance: float,
    new_collateral: float,
    extra: dict[str, Any] | None = None,
) -> dict | None:
    """Update brain_wallet.{balance, collateral_reserved} + optional fields.

    Returns the updated row (for its updated_at, etc.). Clamps both values
    to non-negative before writing.
    """
    patch: dict[str, Any] = {
        "balance": round(_clamp_nonnegative(new_balance, "balance"), 4),
        "collateral_reserved": round(_clamp_nonnegative(new_collateral, "collateral_reserved"), 4),
    }
    if extra:
        patch.update(extra)
    result = (
        get_client()
        .table("brain_wallet")
        .update(patch)
        .eq("user_id", user_id)
        .execute()
    )
    return result.data[0] if result.data else None


def _settle(
    uid: str,
    *,
    txn_type: str,
    balance_delta: float,
    collateral_delta: float,
    ledger_amount: float,
    description: str,
    trade_id: str | None = None,
    symbol: str | None = None,
    shares: float | None = None,
    price: float | None = None,
) -> None:
    """Shared settlement path for every trade-driven wallet mutation.

    Collapses what used to be six near-identical functions into one.
    Each public settlement shim (debit_for_long_buy, credit_for_long_sell,
    etc.) just computes the deltas + audit fields and forwards here —
    the locking, wallet read, update, and ledger write happen once.

    Args:
        balance_delta: signed change to wallet.balance (negative = debit)
        collateral_delta: signed change to wallet.collateral_reserved
        ledger_amount: the signed amount to record on the ledger row.
            Same as balance_delta for most types; differs for SHORT_COVER
            where the ledger reflects the gross credit (allocation + pnl).
    """
    with _user_lock(uid):
        wlt = get_wallet(uid)
        if not wlt:
            logger.error(f"{txn_type}: wallet unavailable for {symbol or uid}")
            return

        new_balance = float(wlt["balance"]) + balance_delta
        new_collateral = float(wlt["collateral_reserved"]) + collateral_delta
        _apply_update(uid, new_balance, new_collateral)
        _write_transaction(
            user_id=uid,
            transaction_type=txn_type,
            amount=ledger_amount,
            balance_after=max(new_balance, 0.0),
            collateral_after=max(new_collateral, 0.0),
            trade_id=trade_id,
            symbol=symbol,
            shares=shares,
            price=price,
            description=description,
        )


# ── Position sizing ─────────────────────────────────────────────────

def calc_position_size_usd(
    wallet_balance: float,
    tier: int,
    trust_multiplier: float | None,
) -> float:
    """Compute dollar allocation for a new brain entry, respecting tiers and caps.

    Rules (see module docstring for the full table):
      • Tier 1 + trust_multiplier 1.0 → wallet_position_pct_tier1 (10%)
      • Tier 1 + trust_multiplier 0.5 → half of that (5%)
      • Tier 2 / Tier 3                → wallet_position_pct_tier2_3 (5%)
      • Hard cap                       → wallet_max_position_pct (15%)
      • Below wallet_min_balance_for_trade → return 0 (caller should skip)

    The result is a dollar amount, not a share count. Caller divides by
    entry price to get fractional shares.
    """
    if wallet_balance < settings.wallet_min_balance_for_trade:
        return 0.0

    trust = float(trust_multiplier) if trust_multiplier is not None else 1.0

    if tier == 1:
        base_pct = settings.wallet_position_pct_tier1
    else:
        base_pct = settings.wallet_position_pct_tier2_3

    # Apply trust_multiplier to Tier 1 only. Tier 2/3 already carry the
    # half-size intent in the config default, so applying trust again would
    # double-discount them.
    if tier == 1 and trust < 1.0:
        base_pct = base_pct * trust

    # Hard cap
    pct = min(base_pct, settings.wallet_max_position_pct)
    allocation = wallet_balance * (pct / 100.0)

    # One more sanity floor: if the computed allocation is smaller than the
    # trade-minimum, skip rather than opening a $1 position.
    if allocation < settings.wallet_min_balance_for_trade:
        return 0.0

    return round(allocation, 2)


# ── Deposits / withdrawals (user-driven) ────────────────────────────

def deposit(user_id: str | None, amount: float, note: str | None = None) -> dict:
    """Credit the wallet with cash and grow the ROI capital basis.

    `initial_deposit` is the committed-capital basis (the ROI denominator).
    It grows dollar-for-dollar with every deposit and shrinks with every
    withdrawal so ROI reflects market moves, not cash flow.

    On the FIRST deposit we ALSO snapshot the current mark-to-market of
    any open legacy brain positions (pre-wallet 1-share holdings) and
    fold that into the baseline. When a legacy position later closes
    and its proceeds flow into the wallet, it's not mistaken for a gain.

    Raises ValueError if amount <= 0.
    Raises LegacySnapshotFailed if the first-deposit snapshot fails with
    legacy positions present — we must not silently baseline at cash-only
    when legacy exists, or every legacy close would read as free money.
    """
    if amount <= 0:
        raise ValueError(f"Deposit amount must be positive, got {amount}")

    uid = _resolve_user_id(user_id)
    if not uid:
        raise RuntimeError("No user available — cannot deposit")

    with _user_lock(uid):
        wlt = get_wallet(uid)
        if not wlt:
            raise RuntimeError("Wallet could not be resolved or created")

        # On first deposit, snapshot legacy holdings. If this fails and
        # legacy positions exist, refuse the deposit — we can't safely
        # baseline at cash-only because legacy closes would then inflate
        # ROI. Retry when the price feed recovers.
        is_first = float(wlt["initial_deposit"]) == 0
        legacy_snapshot = 0.0
        if is_first and _has_legacy_brain_positions(uid):
            # Lazy import: virtual_portfolio imports wallet, so we must
            # not import it at module load. strict=True raises
            # LegacySnapshotFailed on failure; the API maps that to 503.
            from app.services.virtual_portfolio import calculate_brain_holdings_value
            legacy_snapshot = calculate_brain_holdings_value(uid, legacy_only=True, strict=True)

        new_balance = float(wlt["balance"]) + amount
        new_total_deposited = float(wlt["total_deposited"]) + amount
        # Capital basis grows with this deposit. On the first deposit the
        # initial cash PLUS the legacy snapshot become the starting basis;
        # on subsequent deposits we just add the cash amount.
        prev_basis = float(wlt["initial_deposit"])
        if is_first:
            new_basis = amount + legacy_snapshot
        else:
            new_basis = prev_basis + amount

        extra: dict[str, Any] = {
            "total_deposited": round(new_total_deposited, 4),
            "initial_deposit": round(new_basis, 4),
        }

        updated = _apply_update(uid, new_balance, float(wlt["collateral_reserved"]), extra=extra)
        _write_transaction(
            user_id=uid,
            transaction_type=TxnType.DEPOSIT,
            amount=amount,
            balance_after=new_balance,
            collateral_after=float(wlt["collateral_reserved"]),
            description=note or ("Initial deposit" if is_first else "Deposit"),
        )

        # On first deposit with open legacy positions, write an
        # informational ledger row so the audit trail explains WHY the
        # capital basis was bigger than the cash amount.
        if is_first and legacy_snapshot > 0:
            _write_transaction(
                user_id=uid,
                transaction_type=TxnType.LEGACY_BASELINE,
                amount=0.0,
                balance_after=new_balance,
                collateral_after=float(wlt["collateral_reserved"]),
                description=(
                    f"Legacy holdings snapshot at wallet launch: "
                    f"${legacy_snapshot:.2f} added to ROI baseline "
                    f"(pre-wallet 1-share positions)"
                ),
            )

        logger.info(
            f"Wallet DEPOSIT ${amount:.2f} for user {uid} — "
            f"balance ${wlt['balance']:.2f} → ${new_balance:.2f}, "
            f"basis ${prev_basis:.2f} → ${new_basis:.2f}"
            + (f" (first: +${legacy_snapshot:.2f} legacy)" if is_first and legacy_snapshot > 0 else "")
        )
        return updated or {}


def withdraw(user_id: str | None, amount: float, note: str | None = None) -> dict:
    """Debit the wallet and shrink the ROI capital basis.

    Collateral is NOT withdrawable — only free balance. This mirrors a
    real brokerage: money locked against open shorts is not available
    for withdrawal until the positions cover.

    `initial_deposit` (capital basis) shrinks by the withdrawn amount so
    ROI continues to reflect only market moves on remaining capital.
    Clamped to 0 — a withdrawal that exceeds remaining basis means
    you've also pulled out realized gains, and the basis goes to zero.
    """
    if amount <= 0:
        raise ValueError(f"Withdraw amount must be positive, got {amount}")

    uid = _resolve_user_id(user_id)
    if not uid:
        raise RuntimeError("No user available — cannot withdraw")

    with _user_lock(uid):
        wlt = get_wallet(uid)
        if not wlt:
            raise RuntimeError("Wallet could not be resolved")

        free = float(wlt["balance"])
        if amount > free:
            raise ValueError(
                f"Insufficient free balance: requested ${amount:.2f}, available ${free:.2f} "
                f"(${wlt['collateral_reserved']:.2f} is reserved for open shorts)"
            )

        new_balance = free - amount
        new_total_withdrawn = float(wlt["total_withdrawn"]) + amount
        prev_basis = float(wlt["initial_deposit"])
        new_basis = max(0.0, prev_basis - amount)
        updated = _apply_update(
            uid,
            new_balance,
            float(wlt["collateral_reserved"]),
            extra={
                "total_withdrawn": round(new_total_withdrawn, 4),
                "initial_deposit": round(new_basis, 4),
            },
        )
        _write_transaction(
            user_id=uid,
            transaction_type=TxnType.WITHDRAW,
            amount=-amount,
            balance_after=new_balance,
            collateral_after=float(wlt["collateral_reserved"]),
            description=note or "Withdrawal",
        )
        logger.info(
            f"Wallet WITHDRAW ${amount:.2f} for user {uid} — "
            f"balance ${free:.2f} → ${new_balance:.2f}, "
            f"basis ${prev_basis:.2f} → ${new_basis:.2f}"
        )
        return updated or {}


# ── Trade-driven mutations (called from virtual_portfolio) ──────────

def _reason_suffix(exit_reason: str) -> str:
    return f", {exit_reason}" if exit_reason else ""


def debit_for_long_buy(
    user_id: str | None,
    allocation_usd: float,
    trade_id: str | None,
    symbol: str,
    shares: float,
    price: float,
) -> None:
    """Deduct allocation from balance when a LONG brain trade opens."""
    uid = _resolve_user_id(user_id)
    if not uid:
        logger.error(f"debit_for_long_buy: no user_id — cannot settle wallet for {symbol}")
        return
    _settle(
        uid,
        txn_type=TxnType.BUY,
        balance_delta=-allocation_usd,
        collateral_delta=0.0,
        ledger_amount=-allocation_usd,
        trade_id=trade_id,
        symbol=symbol,
        shares=shares,
        price=price,
        description=f"BUY {shares:.4f} {symbol} @ ${price:.2f}",
    )


def credit_for_long_sell(
    user_id: str | None,
    proceeds_usd: float,
    pnl_usd: float,
    trade_id: str | None,
    symbol: str,
    shares: float,
    price: float,
    exit_reason: str = "",
) -> None:
    """Credit proceeds when a LONG brain trade closes."""
    uid = _resolve_user_id(user_id)
    if not uid:
        logger.error(f"credit_for_long_sell: no user_id — cannot settle wallet for {symbol}")
        return
    _settle(
        uid,
        txn_type=TxnType.SELL,
        balance_delta=proceeds_usd,
        collateral_delta=0.0,
        ledger_amount=proceeds_usd,
        trade_id=trade_id,
        symbol=symbol,
        shares=shares,
        price=price,
        description=(
            f"SELL {shares:.4f} {symbol} @ ${price:.2f} "
            f"(P&L ${pnl_usd:+.2f}{_reason_suffix(exit_reason)})"
        ),
    )


def reserve_for_short_open(
    user_id: str | None,
    allocation_usd: float,
    trade_id: str | None,
    symbol: str,
    shares: float,
    price: float,
) -> None:
    """Lock collateral when a SHORT opens. Money moves balance → collateral_reserved."""
    uid = _resolve_user_id(user_id)
    if not uid:
        logger.error(f"reserve_for_short_open: no user_id — cannot settle for {symbol}")
        return
    _settle(
        uid,
        txn_type=TxnType.SHORT_OPEN,
        balance_delta=-allocation_usd,
        collateral_delta=allocation_usd,
        ledger_amount=-allocation_usd,
        trade_id=trade_id,
        symbol=symbol,
        shares=shares,
        price=price,
        description=f"SHORT_OPEN {shares:.4f} {symbol} @ ${price:.2f} (${allocation_usd:.2f} reserved)",
    )


def release_for_short_cover(
    user_id: str | None,
    original_allocation_usd: float,
    pnl_usd: float,
    trade_id: str | None,
    symbol: str,
    shares: float,
    price: float,
    exit_reason: str = "",
) -> None:
    """Release collateral + P&L when a SHORT covers. Net wallet change = P&L."""
    uid = _resolve_user_id(user_id)
    if not uid:
        logger.error(f"release_for_short_cover: no user_id — cannot settle for {symbol}")
        return
    net_credit = original_allocation_usd + pnl_usd
    _settle(
        uid,
        txn_type=TxnType.SHORT_COVER,
        balance_delta=net_credit,
        collateral_delta=-original_allocation_usd,
        ledger_amount=net_credit,
        trade_id=trade_id,
        symbol=symbol,
        shares=shares,
        price=price,
        description=(
            f"SHORT_COVER {shares:.4f} {symbol} @ ${price:.2f} "
            f"(P&L ${pnl_usd:+.2f}{_reason_suffix(exit_reason)})"
        ),
    )


# ── Legacy-close settlement (pre-wallet 1-share positions) ─────────
#
# Legacy positions opened before the wallet existed (is_wallet_trade=False)
# don't have a wallet debit to match against. When they close, we still
# credit the wallet with the proceeds — treating it like "I sold the
# 1-share position I had sitting in holdings, cash goes into my pocket."
# The ledger entry uses a distinct LEGACY_SELL / LEGACY_COVER type so
# reconstruction can tell these apart from normal wallet trades.
#
# The position's per-share pnl is recorded on virtual_trades in the
# normal way by close_virtual_trade — the helpers below only move cash.

def credit_for_legacy_sell(
    user_id: str | None,
    exit_price: float,
    trade_id: str | None,
    symbol: str,
    exit_reason: str = "",
    pnl_usd: float | None = None,
) -> None:
    """Credit 1 × exit_price into the wallet when a pre-wallet LONG closes.

    `pnl_usd` is the per-share realized P&L (exit - entry). Optional
    for backward compat but caller should pass it whenever known so
    the ledger row carries enough context to render win/loss in UI.
    """
    uid = _resolve_user_id(user_id)
    if not uid:
        logger.error(f"credit_for_legacy_sell: no user_id — cannot settle for {symbol}")
        return
    proceeds = float(exit_price)
    pnl_str = f", P&L ${pnl_usd:+.2f}" if pnl_usd is not None else ""
    _settle(
        uid,
        txn_type=TxnType.LEGACY_SELL,
        balance_delta=proceeds,
        collateral_delta=0.0,
        ledger_amount=proceeds,
        trade_id=trade_id,
        symbol=symbol,
        shares=1.0,
        price=proceeds,
        description=(
            f"Legacy sale: {symbol} @ ${proceeds:.2f}{pnl_str} "
            f"(pre-wallet 1-share position{_reason_suffix(exit_reason)})"
        ),
    )


def credit_for_legacy_cover(
    user_id: str | None,
    pnl_usd: float,
    trade_id: str | None,
    symbol: str,
    exit_reason: str = "",
) -> None:
    """Credit the per-share P&L when a pre-wallet SHORT covers.

    No collateral was ever reserved for legacy shorts, so the only cash
    event is the signed P&L — positive means the short was profitable.
    """
    uid = _resolve_user_id(user_id)
    if not uid:
        logger.error(f"credit_for_legacy_cover: no user_id — cannot settle for {symbol}")
        return
    amount = float(pnl_usd)
    _settle(
        uid,
        txn_type=TxnType.LEGACY_COVER,
        balance_delta=amount,
        collateral_delta=0.0,
        ledger_amount=amount,
        trade_id=trade_id,
        symbol=symbol,
        shares=1.0,
        description=(
            f"Legacy cover: {symbol} P&L ${amount:+.2f} "
            f"(pre-wallet 1-share short{_reason_suffix(exit_reason)})"
        ),
    )


# ── Reporting helpers (used by API + performance page) ──────────────

def list_transactions(user_id: str | None, limit: int = 50, offset: int = 0) -> list[dict]:
    """Page through the audit ledger, newest first."""
    uid = _resolve_user_id(user_id)
    if not uid:
        return []
    result = (
        get_client()
        .table("wallet_transactions")
        .select("*")
        .eq("user_id", uid)
        .order("created_at", desc=True)
        .range(offset, offset + max(0, limit - 1))
        .execute()
    )
    return result.data or []


def wallet_state(user_id: str | None) -> dict:
    """Return raw wallet state WITHOUT open-position mark-to-market.

    Use this when you just want balance/collateral/deposit stats — no
    yfinance round trip. Returned by POST /wallet/deposit and /withdraw
    so the response is immediate and honest about what it knows.
    """
    uid = _resolve_user_id(user_id)
    wlt = get_wallet(uid)
    if not wlt:
        return {
            "balance": 0.0,
            "collateral_reserved": 0.0,
            "initial_deposit": 0.0,
            "total_deposited": 0.0,
            "total_withdrawn": 0.0,
            "updated_at": None,
        }
    return {
        "balance": round(float(wlt["balance"]), 2),
        "collateral_reserved": round(float(wlt["collateral_reserved"]), 2),
        "initial_deposit": round(float(wlt["initial_deposit"]), 2),
        "total_deposited": round(float(wlt["total_deposited"]), 2),
        "total_withdrawn": round(float(wlt["total_withdrawn"]), 2),
        "updated_at": wlt.get("updated_at"),
    }


def wallet_summary(
    user_id: str | None,
    open_positions_value: float = 0.0,
) -> dict:
    """Assemble the full /api/v1/wallet response: balance, reserved, total, ROI.

    `open_positions_value` is the current mark-to-market value of open
    wallet LONG positions (sum of shares × current_price). The caller
    passes it in because this module doesn't know about virtual_trades
    or price fetching — keeps the wallet layer decoupled from portfolio
    logic. If not provided, total_value = balance + collateral and the
    returned `roi_pct` UNDERCOUNTS by any unrealized gains on open
    positions — so prefer passing the real value when possible.
    """
    state = wallet_state(user_id)
    if not state.get("updated_at") and state["balance"] == 0 and state["initial_deposit"] == 0:
        # No wallet row at all (get_wallet returned None). Preserve the
        # zero shape so callers can render a "fund your wallet" state.
        return {
            **state,
            "total_value": 0.0,
            "roi_pct": 0.0,
            "open_positions_value": 0.0,
        }

    balance = state["balance"]
    collateral = state["collateral_reserved"]
    initial = state["initial_deposit"]
    total_value = balance + collateral + float(open_positions_value or 0)
    # ROI = (current total - first deposit) / first deposit.
    # Tops-ups after the initial deposit don't reset the baseline, so ROI
    # stays interpretable as "return on the money I committed".
    roi = ((total_value - initial) / initial * 100) if initial > 0 else 0.0

    return {
        **state,
        "total_value": round(total_value, 2),
        "roi_pct": round(roi, 2),
        "open_positions_value": round(float(open_positions_value or 0), 2),
    }


def _has_legacy_brain_positions(user_id: str) -> bool:
    """True if there are any open pre-wallet 1-share brain positions.

    Used before the strict-mode snapshot: if there are none, a price-fetch
    failure is benign (legacy value is 0). If there ARE, a failure must
    NOT silently return 0 — that would inflate ROI once they liquidate.
    """
    try:
        result = (
            get_client()
            .table("virtual_trades")
            .select("id")
            .eq("user_id", user_id)
            .eq("status", "OPEN")
            .eq("source", "brain")
            .eq("is_wallet_trade", False)
            .limit(1)
            .execute()
        )
        return bool(result.data)
    except Exception as e:
        logger.warning(f"_has_legacy_brain_positions query failed: {e}")
        # If we can't tell, assume yes to force strict — safer to refuse
        # a deposit than to silently baseline wrong.
        return True


# Mark-to-market math lives in virtual_portfolio.py (that's where
# virtual_trades schema knowledge belongs). Callers import from there
# directly; no re-export through wallet.py.
