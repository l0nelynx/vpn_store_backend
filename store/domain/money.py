"""Currency helpers with no database imports."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from xml.etree import ElementTree

TRACKED_CBR = ("USD", "EUR")


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


def parse_cbr_daily_xml(payload: str | bytes) -> tuple[date, dict[str, Decimal]]:
    if isinstance(payload, bytes):
        text = payload.decode("windows-1251")
    else:
        text = payload
    root = ElementTree.fromstring(text)
    raw_date = root.attrib.get("Date") or ""
    rate_date = datetime.strptime(raw_date, "%d.%m.%Y").date() if raw_date else date.today()
    rates: dict[str, Decimal] = {}
    for valute in root.findall("Valute"):
        code = (valute.findtext("CharCode") or "").strip().upper()
        if code not in TRACKED_CBR:
            continue
        nominal = as_decimal(valute.findtext("Nominal")) or Decimal("1")
        value = as_decimal(valute.findtext("Value"))
        if value is None or nominal <= 0:
            continue
        rates[code] = value / nominal
    return rate_date, rates
