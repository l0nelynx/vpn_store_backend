"""Verified marketplace order synchronization."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiohttp
from sqlalchemy import select

from store.database.models import SyncCheckpoint, async_session
from store.domain.pipeline import PipelineError
from store.integrations.providers import digiseller, ggsel
from store.services.runtime import execute_run, ingest_ggsel_purchase, ingest_order

logger = logging.getLogger(__name__)


def _ggsel_order_content(info: dict, invoice_id: str | int) -> dict:
    """Normalize info_order without conflating invoice and chat identifiers.

    Seller API V1 returns ``invoice_id`` in seller-last-sales, while the
    purchase/info response content starts with ``item_id`` and ``content_id``.
    Preserve the verified lookup key explicitly for ingestion/idempotency.
    """
    payload = info.get("content") or info
    if not isinstance(payload, dict):
        return {}
    content = dict(payload)
    content.setdefault("invoice_id", invoice_id)
    return content


async def _checkpoint(provider: str, seen_ids: list[str], *, success: bool, detail: str | None = None) -> None:
    async with async_session() as session:
        row = await session.scalar(
            select(SyncCheckpoint).where(
                SyncCheckpoint.provider == provider, SyncCheckpoint.stream == "orders"
            )
        )
        if not row:
            row = SyncCheckpoint(provider=provider, stream="orders", cursor={})
            session.add(row)
        previous = str((row.cursor or {}).get("last_id") or "")
        # A bounded recent-sales window can no longer prove continuity if the
        # last checkpoint disappeared from the overlap window.
        row.gap_detected = bool(previous and seen_ids and previous not in seen_ids)
        if seen_ids:
            row.cursor = {"last_id": seen_ids[0], "window_ids": seen_ids[:200]}
            row.last_seen_at = datetime.now(timezone.utc)
        if success:
            row.last_success_at = datetime.now(timezone.utc)
        row.detail = detail
        await session.commit()


async def sync_ggsel_orders(top: int = 50) -> dict:
    imported = delivered = fulfilled = skipped = errors = 0
    seen: list[str] = []
    async with aiohttp.ClientSession() as http:
        try:
            sales = await ggsel.recent_sales(http, top=top)
            for sale in sales:
                invoice_id = sale.get("invoice_id")
                if invoice_id is None:
                    skipped += 1
                    continue
                seen.append(str(invoice_id))
                try:
                    info = await ggsel.purchase(http, invoice_id)
                    content = _ggsel_order_content(info, invoice_id)
                    state = ggsel.normalize_state(content.get("invoice_state"))
                    if state not in {"paid", "fulfilled"}:
                        skipped += 1
                        continue
                    order, run, created = await ingest_ggsel_purchase(content, sale)
                    imported += int(created)
                    if state == "fulfilled":
                        fulfilled += int(created)
                        continue
                    if order.delivery_status == 1 or order.normalized_status in {"delivered", "fulfilled"}:
                        # A marketplace may keep returning state=3 after the
                        # legacy service already delivered the order.
                        skipped += 1
                        continue
                    if run:
                        result = await execute_run(run.id)
                        delivered += int(result.get("status") in {"delivered", "delivered_with_warnings"})
                except PipelineError as exc:
                    if exc.permanent:
                        skipped += 1
                    else:
                        errors += 1
                    logger.warning("GGSel invoice %s: %s", invoice_id, exc)
                except Exception:
                    errors += 1
                    logger.exception("GGSel invoice %s failed", invoice_id)
            await _checkpoint("ggsel", seen, success=True)
        except Exception as exc:
            errors += 1
            await _checkpoint("ggsel", seen, success=False, detail=str(exc))
            logger.exception("GGSel sync failed")
    return {"marketplace": "ggsel", "top": top, "imported": imported, "delivered": delivered,
            "fulfilled_imported": fulfilled, "skipped": skipped, "errors": errors}


async def sync_digiseller_orders(top: int = 50) -> dict:
    """Reconciliation only; supplier webhook remains the primary trigger."""
    imported = skipped = errors = 0
    seen: list[str] = []
    async with aiohttp.ClientSession() as http:
        try:
            token = await digiseller.token(http)
            params = {"seller_id": digiseller.seller_id, "top": top, "token": token}
            async with http.get(f"{digiseller.base_url}/api/seller-last-sales", params=params) as response:
                data = await response.json(content_type=None)
                if response.status >= 400:
                    raise RuntimeError(f"Digiseller last-sales HTTP {response.status}")
            for sale in data.get("sales") or []:
                inv = sale.get("invoice_id") or sale.get("inv") or sale.get("id_i")
                if inv is None:
                    skipped += 1
                    continue
                seen.append(str(inv))
                try:
                    info = await digiseller.purchase(http, inv)
                    content = info.get("content") or info
                    state = digiseller.normalize_state(content.get("invoice_state") or content.get("state"))
                    item_id = content.get("id_goods") or content.get("id") or sale.get("id_goods")
                    if state not in {"paid", "refund"} or item_id is None:
                        skipped += 1
                        continue
                    buyer = content.get("buyer_info") or {}
                    _, _, created = await ingest_order(
                        provider="digiseller", provider_order_id=str(inv), item_id=int(item_id), payload=content,
                        normalized_status=state, invoice_id=str(inv), email=buyer.get("email"),
                        buyer_id=str(buyer.get("buyer_id") or "") or None, options=content.get("options") or [],
                        chat_id=str(inv), **digiseller.money_fields(content),
                    )
                    imported += int(created)
                except Exception:
                    errors += 1
                    logger.exception("Digiseller reconciliation inv=%s failed", inv)
            await _checkpoint("digiseller", seen, success=True)
        except Exception as exc:
            errors += 1
            await _checkpoint("digiseller", seen, success=False, detail=str(exc))
    return {"marketplace": "digiseller", "top": top, "imported": imported,
            "skipped": skipped, "errors": errors}


async def sync_all_orders(top: int = 50) -> dict:
    return {"ggsel": await sync_ggsel_orders(top), "digiseller": await sync_digiseller_orders(top)}
