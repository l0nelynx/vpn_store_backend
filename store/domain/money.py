"""Currency helpers with no database imports."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any


def as_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


RUB_CODES = {"RUB", "RUR", "WMR", ""}
USD_CODES = {"USD", "WMZ"}
EUR_CODES = {"EUR", "WME"}


def canonical_money_currency(raw: Any) -> str:
    if raw in (None, ""):
        return ""
    code = str(raw).strip().upper()
    return {
        "WMR": "RUB",
        "RUR": "RUB",
        "RUB": "RUB",
        "WMZ": "USD",
        "USD": "USD",
        "WME": "EUR",
        "EUR": "EUR",
    }.get(code, code)


def quote_order_revenue_rub(
    *,
    net_rub: Any = None,
    profit_amount: Any = None,
    net_amount: Any = None,
    gross_amount: Any = None,
    amount: Any = None,
    amount_usd: Any = None,
    currency: Any = None,
    net_currency: Any = None,
    usd_rate: Decimal | None = None,
    eur_rate: Decimal | None = None,
) -> Decimal:
    """Net proceeds in RUB. USD/EUR source amounts are converted; stored rubles are kept."""
    stored = as_decimal(net_rub)
    native = as_decimal(profit_amount) or as_decimal(net_amount) or as_decimal(gross_amount) or as_decimal(amount)
    usd = as_decimal(amount_usd)
    curr = canonical_money_currency(net_currency or currency)
    usd_rate = usd_rate if usd_rate and usd_rate > 0 else None
    eur_rate = eur_rate if eur_rate and eur_rate > 0 else None

    def as_usd_rub(source: Decimal | None) -> Decimal | None:
        if source is None or usd_rate is None:
            return None
        return source * usd_rate

    if curr in USD_CODES:
        source = native if native is not None else usd if usd is not None else stored
        return as_usd_rub(source) or Decimal("0")
    if curr in EUR_CODES:
        source = native if native is not None else stored
        if source is not None and eur_rate:
            return source * eur_rate
        return source or Decimal("0")
    if looks_unconverted_usd(stored if stored is not None else native, usd):
        source = native if native is not None else usd
        if usd is not None and native is not None and native == stored:
            source = usd
        return as_usd_rub(source) or Decimal("0")
    if stored is not None and stored > 0:
        return stored
    if usd is not None:
        converted = as_usd_rub(usd)
        if converted is not None:
            return converted
    return stored or native or Decimal("0")


def looks_unconverted_usd(native: Any, amount_usd: Any) -> bool:
    """True when a stored total is the USD figure rather than rubles."""
    usd = as_decimal(amount_usd)
    value = as_decimal(native)
    if usd is None or usd <= 0:
        return False
    if value is None:
        return True
    return value <= usd * Decimal("2")


def _usd_map_to_quote_rates(usd_to: dict[str, Any]) -> dict[str, Decimal]:
    by_code = {str(key).upper(): as_decimal(value) for key, value in usd_to.items()}
    rub = by_code.get("RUB")
    eur = by_code.get("EUR")
    rates: dict[str, Decimal] = {}
    if rub and rub > 0:
        rates["USD"] = rub
        if eur and eur > 0:
            rates["EUR"] = rub / eur
    return rates


def parse_jsdelivr_usd_json(payload: dict[str, Any]) -> tuple[date, dict[str, Decimal]]:
    raw_date = str(payload.get("date") or "")
    try:
        rate_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
    except ValueError:
        rate_date = date.today()
    usd_to = payload.get("usd") if isinstance(payload.get("usd"), dict) else {}
    return rate_date, _usd_map_to_quote_rates(usd_to)


def parse_open_er_api_json(payload: dict[str, Any]) -> tuple[date, dict[str, Decimal]]:
    raw = payload.get("time_last_update_utc") or payload.get("date") or ""
    rate_date = date.today()
    if isinstance(raw, str) and raw:
        for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%d"):
            try:
                rate_date = datetime.strptime(raw, fmt).date()
                break
            except ValueError:
                continue
    quotes = payload.get("rates") if isinstance(payload.get("rates"), dict) else {}
    return rate_date, _usd_map_to_quote_rates(quotes)
