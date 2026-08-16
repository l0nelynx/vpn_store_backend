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
