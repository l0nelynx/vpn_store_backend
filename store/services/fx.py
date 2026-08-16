"""USD/EUR to RUB quotes from public HTTPS APIs outside Russia."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any

import aiohttp
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.dialects.postgresql import insert

from store.database.models import FxRate, Order, async_session
from store.domain.money import as_decimal, looks_unconverted_usd, parse_jsdelivr_usd_json, parse_open_er_api_json
from store.integrations.providers import canonical_currency

logger = logging.getLogger(__name__)

# Cloudflare / jsDelivr first; ExchangeRate-API (open.er-api.com) as fallback.
# Russian and government hosts are intentionally not used.
FX_SOURCES = (
    (
        "jsdelivr",
        "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.min.json",
        parse_jsdelivr_usd_json,
    ),
    (
        "cloudflare-pages",
        "https://latest.currency-api.pages.dev/v1/currencies/usd.min.json",
        parse_jsdelivr_usd_json,
    ),
    (
        "open-er-api",
        "https://open.er-api.com/v6/latest/USD",
        parse_open_er_api_json,
    ),
)
_HEADERS = {"Accept": "application/json", "User-Agent": "vpn-store-backend/2.0"}
RUB_CODES = {"RUB", "RUR", "WMR"}
USD_CODES = {"USD", "WMZ"}
EUR_CODES = {"EUR", "WME"}
_refresh_lock = asyncio.Lock()


def _rate_datetime(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


async def fetch_fx_rates() -> tuple[date, dict[str, Decimal], str]:
    timeout = aiohttp.ClientTimeout(total=12)
    errors: list[str] = []
    async with aiohttp.ClientSession(timeout=timeout, headers=_HEADERS) as http:
        for source, url, parser in FX_SOURCES:
            try:
                async with http.get(url) as response:
                    if response.status >= 400:
                        errors.append(f"{source} HTTP {response.status}")
                        continue
                    payload = await response.json(content_type=None)
                if not isinstance(payload, dict):
                    errors.append(f"{source} invalid json")
                    continue
                rate_date, rates = parser(payload)
                if "USD" in rates:
                    return rate_date, rates, source
                errors.append(f"{source} missing USD/RUB")
            except Exception as exc:
                errors.append(f"{source}: {exc}")
    raise RuntimeError("FX providers failed: " + "; ".join(errors))


async def refresh_fx_rates() -> dict[str, Decimal]:
    async with _refresh_lock:
        rate_date, rates, source = await fetch_fx_rates()
        if not rates:
            return {}
        moment = _rate_datetime(rate_date)
        async with async_session() as session:
            for code, rate in rates.items():
                stmt = insert(FxRate).values(
                    rate_date=moment,
                    base_currency=code,
                    quote_currency="RUB",
                    rate=rate,
                    source=source,
                )
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_fx_rates_key",
                    set_={"rate": rate, "source": source},
                )
                await session.execute(stmt)
            await session.commit()
        logger.info("FX rates %s from %s: %s", rate_date.isoformat(), source, rates)
        return rates


async def ensure_fx_rates() -> dict[str, Decimal]:
    async with async_session() as session:
        if await latest_rate(session, "USD"):
            return {}
    try:
        return await refresh_fx_rates()
    except Exception:
        logger.exception("FX rate warmup failed")
        return {}


async def latest_rate(session, base: str) -> FxRate | None:
    code = canonical_currency(base) or str(base or "").upper()
    if not code or code in RUB_CODES:
        return None
    return await session.scalar(
        select(FxRate)
        .where(FxRate.base_currency == code, FxRate.quote_currency == "RUB")
        .order_by(FxRate.rate_date.desc())
        .limit(1)
    )


async def ensure_rate(session, base: str) -> FxRate | None:
    rate = await latest_rate(session, base)
    if rate:
        return rate
    code = canonical_currency(base) or str(base or "").upper()
    if not code or code in RUB_CODES:
        return None
    try:
        await refresh_fx_rates()
    except Exception:
        logger.exception("FX refresh failed for %s", code)
        return None
    return await latest_rate(session, code)


def _latest_rate_subquery(base: str):
    return (
        select(FxRate.rate)
        .where(FxRate.base_currency == base, FxRate.quote_currency == "RUB")
        .order_by(FxRate.rate_date.desc())
        .limit(1)
        .scalar_subquery()
    )


def revenue_rub_expr():
    """Ruble net proceeds: never treat USD/EUR source amounts as rubles."""
    curr = func.upper(func.coalesce(Order.net_currency, Order.currency, ""))
    native = func.coalesce(Order.profit_amount, Order.net_amount, Order.gross_amount, Order.amount)
    usd_rate = _latest_rate_subquery("USD")
    eur_rate = _latest_rate_subquery("EUR")
    unconverted = and_(
        Order.amount_usd.is_not(None),
        Order.amount_usd > 0,
        func.coalesce(Order.net_rub, native).is_not(None),
        func.coalesce(Order.net_rub, native) <= Order.amount_usd * 2,
    )
    trusted_rub = case((unconverted, None), else_=Order.net_rub)
    rub_native = case(
        (and_(or_(curr.in_(tuple(RUB_CODES)), curr == ""), ~unconverted), native),
        else_=None,
    )
    return func.coalesce(
        trusted_rub,
        rub_native,
        Order.amount_usd * usd_rate,
        case((curr.in_(tuple(USD_CODES)), native * usd_rate), else_=None),
        case((curr.in_(tuple(EUR_CODES)), native * eur_rate), else_=None),
    )


def gross_rub_expr():
    curr = func.upper(func.coalesce(Order.gross_currency, Order.currency, ""))
    native = func.coalesce(Order.gross_amount, Order.amount)
    usd_rate = _latest_rate_subquery("USD")
    eur_rate = _latest_rate_subquery("EUR")
    unconverted = and_(
        Order.amount_usd.is_not(None),
        Order.amount_usd > 0,
        func.coalesce(Order.gross_rub, native).is_not(None),
        func.coalesce(Order.gross_rub, native) <= Order.amount_usd * 2,
    )
    trusted_rub = case((unconverted, None), else_=Order.gross_rub)
    rub_native = case(
        (and_(or_(curr.in_(tuple(RUB_CODES)), curr == ""), ~unconverted), native),
        else_=None,
    )
    return func.coalesce(
        trusted_rub,
        rub_native,
        Order.amount_usd * usd_rate,
        case((curr.in_(tuple(USD_CODES)), native * usd_rate), else_=None),
        case((curr.in_(tuple(EUR_CODES)), native * eur_rate), else_=None),
    )


async def convert_to_rub(
    session,
    value: Any,
    currency: str | None,
    *,
    amount_usd: Any = None,
    existing_fx_rate_id: int | None = None,
) -> tuple[Decimal | None, FxRate | None, str | None]:
    amount = as_decimal(value)
    usd = as_decimal(amount_usd)
    curr = canonical_currency(currency)
    if curr not in EUR_CODES and looks_unconverted_usd(amount if amount is not None else usd, usd):
        curr = "USD"
        amount = usd
    if amount is None:
        return None, None, curr
    if not curr or curr in RUB_CODES:
        return amount, None, curr or "RUB"
    fx = await session.get(FxRate, existing_fx_rate_id) if existing_fx_rate_id else None
    if fx and canonical_currency(fx.base_currency) != curr:
        fx = None
    if fx is None:
        fx = await ensure_rate(session, curr)
    if fx is None:
        return None, None, curr
    return amount * fx.rate, fx, curr


async def backfill_order_rub_amounts() -> dict[str, int]:
    updated = skipped = 0
    async with async_session() as session:
        rows = (
            await session.scalars(
                select(Order).where(
                    or_(
                        func.upper(func.coalesce(Order.currency, "")).in_(tuple(USD_CODES | EUR_CODES)),
                        and_(Order.amount_usd.is_not(None), Order.amount_usd > 0),
                        Order.net_rub.is_(None),
                    )
                )
            )
        ).all()
        for order in rows:
            native = order.net_amount or order.profit_amount or order.gross_amount or order.amount
            currency = canonical_currency(order.net_currency or order.currency)
            net_rub, fx, curr = await convert_to_rub(
                session,
                native,
                currency,
                amount_usd=order.amount_usd,
                existing_fx_rate_id=order.fx_rate_id,
            )
            if net_rub is None:
                skipped += 1
                continue
            if order.net_rub == net_rub and (not curr or canonical_currency(order.currency) == curr):
                skipped += 1
                continue
            gross_source = order.gross_amount or native
            gross_rub, _, _ = await convert_to_rub(
                session,
                gross_source,
                currency,
                amount_usd=order.amount_usd,
                existing_fx_rate_id=order.fx_rate_id,
            )
            order.net_rub = net_rub
            if gross_rub is not None:
                order.gross_rub = gross_rub
            if curr:
                order.currency = curr
                order.net_currency = curr
                order.gross_currency = curr
            if fx:
                order.fx_rate_id = fx.id
            updated += 1
        await session.commit()
    logger.info("FX ruble backfill: updated=%s skipped=%s", updated, skipped)
    return {"updated": updated, "skipped": skipped}
